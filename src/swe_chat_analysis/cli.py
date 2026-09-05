from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from .env import load_dotenv
from .io import (
    parse_json_list, read_commit_summaries, read_conversations, read_jsonl,
    read_user_prompt_counts, sample_sessions, write_jsonl,
)
from .llm import OpenAICompatibleClient
from .metrics import aggregate, save_summary
from .packet import compact_event, iter_behavior_episode_prefixes, build_packet, packet_as_text
from .rubric import (
    RUBRIC_VERSION, SYSTEM_PROMPT, derive_behavior_modes,
    drop_invalid_evidence_turns, normalize_null_boolean_fields, user_prompt,
    validate_annotation,
)
from .study1 import (
    BEHAVIOR_SYSTEM_PROMPT as STUDY1_BEHAVIOR_SYSTEM_PROMPT,
    REQUIREMENTS_SYSTEM_PROMPT as STUDY1_REQUIREMENTS_SYSTEM_PROMPT,
    STUDY1_REQUIREMENTS_RUBRIC_VERSION,
    STUDY1_RUBRIC_VERSION,
    aggregate_study1,
    behavior_user_prompt as study1_behavior_user_prompt,
    normalize_behavior_annotation as normalize_study1_behavior,
    normalize_requirements_annotation as normalize_study1_requirements,
    requirements_user_prompt as study1_requirements_user_prompt,
    validate_behavior_annotation as validate_study1_behavior,
    validate_requirements_annotation as validate_study1_requirements,
)
from .study2 import (
    STUDY2_RUBRIC_VERSION,
    SYSTEM_PROMPT as STUDY2_SYSTEM_PROMPT,
    aggregate_study2,
    normalize_annotation as normalize_study2_annotation,
    user_prompt as study2_user_prompt,
    validate_annotation as validate_study2_annotation,
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _check_data(data_dir: Path) -> tuple[Path, Path]:
    sessions = data_dir / "sessions.parquet"
    conversations = data_dir / "conversations.parquet"
    missing = [str(path) for path in (sessions, conversations) if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing required SWE-Chat files: " + ", ".join(missing)
            + ". Run scripts/download_data.py after accepting the dataset terms."
        )
    return sessions, conversations


def prepare(args: argparse.Namespace) -> Path:
    if args.sample_size < 0 or args.min_prompts < 1:
        raise ValueError("Require sample-size >= 0 and min-prompts >= 1")
    if args.max_prompts is not None and args.max_prompts < args.min_prompts:
        raise ValueError("max-prompts must be 0 (unlimited) or >= min-prompts")
    if args.max_packet_chars < 1000:
        raise ValueError("max-packet-chars must be at least 1000")
    data_dir, output_dir = Path(args.data_dir), Path(args.output_dir)
    sessions_path, conversations_path = _check_data(data_dir)
    prompt_counts = read_user_prompt_counts(conversations_path)
    sessions = sample_sessions(
        sessions_path, args.sample_size, args.seed, args.min_prompts, args.max_prompts,
        set(args.agent) if args.agent else None, prompt_counts,
    )
    if not sessions:
        raise RuntimeError("No sessions match the sampling filters")
    session_ids = [str(row["session_id"]) for row in sessions]
    conversations = read_conversations(conversations_path, session_ids, compact_event)

    checkpoints = {
        checkpoint
        for session in sessions
        for checkpoint in (
            parse_json_list(session.get("checkpoint_ids"))
            or [str(session.get("canonical_checkpoint_pk") or "")]
        )
        if checkpoint
    }
    commit_map = (
        read_commit_summaries(data_dir / "commits.parquet", checkpoints)
        if not args.no_commits else {}
    )
    packets = []
    for session in sessions:
        session_id = str(session["session_id"])
        events = conversations.pop(session_id, [])
        if not any(event.get("turn_type") == "user_prompt" for event in events):
            continue
        packets.append(build_packet(session, events, commit_map, args.max_packet_chars))
    packet_path = output_dir / "packets.jsonl"
    write_jsonl(packet_path, packets)
    meta = {
        "seed": args.seed,
        "sample_size_requested": args.sample_size,
        "packets_written": len(packets),
        "min_prompts": args.min_prompts,
        "max_prompts": args.max_prompts,
        "agents": args.agent,
        "commits_included": not args.no_commits and (data_dir / "commits.parquet").exists(),
        "sampling_policy": "metadata_prompt_bounds_and_observed_noncontinuation_minimum_v2",
        "max_packet_chars": args.max_packet_chars,
        "expected_behavior_episode_count": sum(len(_packet_user_turns(packet)) for packet in packets),
        "truncated_packet_count": sum(packet["packet_truncated"] for packet in packets),
        "reindexed_packet_count": sum(packet["packet_diagnostics"]["turn_numbers_reindexed"] for packet in packets),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "prepare_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Prepared {len(packets)} packets at {packet_path}")
    return packet_path


def judge(args: argparse.Namespace) -> Path:
    load_dotenv(args.env_file)
    output_dir = Path(args.output_dir)
    packet_path = Path(args.packet_file) if args.packet_file else output_dir / "packets.jsonl"
    packets = read_jsonl(packet_path)
    rejudge_ids = set(args.rejudge_session or [])
    available_ids = {str(packet["session"]["session_id"]) for packet in packets}
    unknown_rejudge_ids = rejudge_ids - available_ids
    if unknown_rejudge_ids:
        raise ValueError(f"rejudge sessions absent from packet file: {sorted(unknown_rejudge_ids)}")
    base_url = args.base_url or os.getenv("OPENAI_BASE_URL")
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    model = args.model or os.getenv("OPENAI_MODEL")
    if not all([base_url, api_key, model]):
        raise RuntimeError(
            "Set OPENAI_BASE_URL, OPENAI_API_KEY, and OPENAI_MODEL in .env"
        )
    client = OpenAICompatibleClient(
        str(base_url), str(api_key), str(model), args.timeout, args.max_retries,
        trust_env_proxy=(
            args.trust_env_proxy
            if args.trust_env_proxy is not None
            else os.getenv("OPENAI_TRUST_ENV_PROXY", "false").lower() in {"1", "true", "yes"}
        ),
    )
    results_path, errors_path = output_dir / "annotations.jsonl", output_dir / "errors.jsonl"
    packet_ids = {str(packet["session"]["session_id"]) for packet in packets}
    existing_by_id = {
        str(row["session_id"]): row
        for row in (read_jsonl(results_path) if args.resume else [])
        if str(row.get("session_id")) in packet_ids
        and str(row.get("session_id")) not in rejudge_ids
    }
    existing_rows = list(existing_by_id.values())
    if args.resume and results_path.exists():
        # Keep a resumed output synchronized with the current packet manifest;
        # otherwise changing seed/sample-size could silently mix experiments.
        write_jsonl(results_path, existing_rows)
    done = {str(row["session_id"]) for row in existing_rows}
    mode = "a" if args.resume else "w"
    output_dir.mkdir(parents=True, exist_ok=True)
    completed = 0
    with results_path.open(mode, encoding="utf-8") as results, errors_path.open(mode, encoding="utf-8") as errors:
        for index, packet in enumerate(packets, 1):
            session_id = str(packet["session"]["session_id"])
            if session_id in done:
                continue
            try:
                annotation, usage = client.complete_json(
                    SYSTEM_PROMPT, user_prompt(packet_as_text(packet))
                )
                valid_turns = {
                    int(turn)
                    for turn in re.findall(r"(?m)^T(\d+) ", str(packet.get("transcript", "")))
                }
                dropped_evidence = drop_invalid_evidence_turns(annotation, valid_turns)
                normalize_null_boolean_fields(annotation)
                derive_behavior_modes(annotation)
                validate_annotation(annotation, valid_turns=valid_turns)
                row = {
                    "session_id": session_id,
                    "repo_id": packet["session"].get("repo_id"),
                    "agent": packet["session"].get("agent"),
                    "dataset_prompt_pushback_counts": packet["session"].get(
                        "dataset_prompt_pushback_counts", {}
                    ),
                    "annotation": annotation,
                    "usage": usage,
                    "model": model,
                    "rubric_version": RUBRIC_VERSION,
                }
                if dropped_evidence:
                    row["validation_warnings"] = {
                        "dropped_invalid_evidence_turns": dropped_evidence,
                    }
                results.write(json.dumps(row, ensure_ascii=False) + "\n")
                results.flush()
                completed += 1
                print(f"[{index}/{len(packets)}] judged {session_id}")
            except Exception as error:
                failure = {"session_id": session_id, "error": str(error), "model": model}
                errors.write(json.dumps(failure, ensure_ascii=False) + "\n")
                errors.flush()
                print(f"[{index}/{len(packets)}] ERROR {session_id}: {error}", file=sys.stderr)
            if args.delay > 0:
                time.sleep(args.delay)
    print(f"Wrote {completed} new annotations to {results_path}")
    return results_path


def _study_client(args: argparse.Namespace) -> tuple[OpenAICompatibleClient, str]:
    load_dotenv(args.env_file)
    base_url = args.base_url or os.getenv("OPENAI_BASE_URL")
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    model = args.model or os.getenv("OPENAI_MODEL")
    if not all([base_url, api_key, model]):
        raise RuntimeError("Set OPENAI_BASE_URL, OPENAI_API_KEY, and OPENAI_MODEL in .env")
    client = OpenAICompatibleClient(
        str(base_url), str(api_key), str(model), args.timeout, args.max_retries,
        trust_env_proxy=(
            args.trust_env_proxy
            if args.trust_env_proxy is not None
            else os.getenv("OPENAI_TRUST_ENV_PROXY", "false").lower() in {"1", "true", "yes"}
        ),
    )
    return client, str(model)


def _packet_turns(packet: dict[str, Any]) -> set[int]:
    return {
        int(turn)
        for turn in re.findall(r"(?m)^T(\d+) ", str(packet.get("transcript", "")))
    }


def _packet_user_turns(packet: dict[str, Any]) -> set[int]:
    return {
        int(turn)
        for turn in re.findall(
            r"(?m)^T(\d+) user_prompt:", str(packet.get("transcript", ""))
        )
    }


def _resume_rows(
    path: Path,
    valid_keys: set[str],
    key_fn: Any,
    rejudge_sessions: set[str],
    resume: bool,
    rubric_version: str | None = None,
    fingerprints: dict[str, str] | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    if not resume:
        return []
    rows = [
        row for row in read_jsonl(path)
        if key_fn(row) in valid_keys
        and str(row.get("session_id")) not in rejudge_sessions
        and (rubric_version is None or row.get("rubric_version") == rubric_version)
        and (fingerprints is None or row.get("input_fingerprint") == fingerprints.get(str(row.get("session_id"))))
        and (model is None or row.get("model") == model)
    ]
    rows = list({key_fn(row): row for row in rows}.values())
    if path.exists():
        write_jsonl(path, rows)
    return rows


def _packet_fingerprint(packet: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(packet, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class AnnotationValidationFailure(ValueError):
    def __init__(
        self,
        initial_error: Exception,
        initial_annotation: dict[str, Any],
        repaired_error: Exception | None = None,
        repaired_annotation: dict[str, Any] | None = None,
    ) -> None:
        message = f"annotation validation failed: initial={initial_error}"
        if repaired_error is not None:
            message += f"; repair={repaired_error}"
        super().__init__(message)
        self.initial_error = str(initial_error)
        self.initial_annotation = initial_annotation
        self.repaired_error = str(repaired_error) if repaired_error is not None else None
        self.repaired_annotation = repaired_annotation


def _failure_record(error: Exception, **fields: Any) -> dict[str, Any]:
    record = {**fields, "error": str(error), "attempted_at_unix": int(time.time())}
    if isinstance(error, AnnotationValidationFailure):
        record["initial_validation_error"] = error.initial_error
        record["initial_invalid_annotation"] = error.initial_annotation
        if error.repaired_error is not None:
            record["repair_error"] = error.repaired_error
        if error.repaired_annotation is not None:
            record["repaired_invalid_annotation"] = error.repaired_annotation
    return record


def _sync_error_log(
    path: Path,
    resume: bool,
    rubric_version: str,
    valid_keys: set[str],
    key_fn: Any,
) -> None:
    """Keep resumed diagnostics scoped to the current sample and rubric."""
    if not resume or not path.exists():
        return
    rows = [
        row for row in read_jsonl(path)
        if row.get("rubric_version") == rubric_version and key_fn(row) in valid_keys
    ]
    write_jsonl(path, rows)


def _complete_validated_json(
    client: OpenAICompatibleClient,
    system_prompt: str,
    prompt: str,
    normalize: Any,
    validate: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Make one schema-repair attempt so deterministic judge errors are resumable."""
    annotation, usage = client.complete_json(system_prompt, prompt)
    try:
        normalize(annotation)
        validate(annotation)
        return annotation, usage
    except (ValueError, TypeError, KeyError, AttributeError) as initial_error:
        repair_prompt = (
            prompt
            + "\n\nYour previous JSON did not pass deterministic validation. Correct only the "
            "schema or inconsistent fields while preserving evidence-grounded judgments.\n"
            + f"VALIDATION_ERROR: {initial_error}\n"
            + "Use only the exact enum values listed in the system prompt.\n"
            + "PREVIOUS_JSON:\n"
            + json.dumps(annotation, ensure_ascii=False)
        )
        try:
            repaired, repair_usage = client.complete_json(system_prompt, repair_prompt)
        except Exception as repair_error:
            raise AnnotationValidationFailure(
                initial_error, annotation, repaired_error=repair_error
            ) from repair_error
        try:
            normalize(repaired)
            validate(repaired)
        except (ValueError, TypeError, KeyError, AttributeError) as repaired_error:
            raise AnnotationValidationFailure(
                initial_error, annotation, repaired_error, repaired
            ) from repaired_error
        return repaired, {"initial": usage, "validation_repair": repair_usage}


def _run_concurrent_jobs(
    jobs: Any, worker: Any, workers: int, delay: float = 0,
) -> Any:
    """Run independent judge jobs while yielding all writes back to the main thread."""
    if workers < 1:
        raise ValueError("workers must be at least 1")

    def run_one(job: Any) -> tuple[Any | None, Exception | None]:
        try:
            return worker(job), None
        except Exception as error:
            return None, error
        finally:
            if delay > 0:
                time.sleep(delay)

    if workers == 1:
        for job in jobs:
            result, error = run_one(job)
            yield job, result, error
        return

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="judge") as executor:
        pending_jobs = iter(jobs)
        futures = {}
        while True:
            while len(futures) < workers:
                try:
                    job = next(pending_jobs)
                except StopIteration:
                    break
                futures[executor.submit(run_one, job)] = job
            if not futures:
                break
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                result, error = future.result()
                yield futures.pop(future), result, error


def _check_study1_output_version(output_dir: Path, resume: bool) -> None:
    if not resume:
        return
    for filename, version in (("requirement_annotations.jsonl", STUDY1_REQUIREMENTS_RUBRIC_VERSION),
                              ("behavior_annotations.jsonl", STUDY1_RUBRIC_VERSION)):
        if any(row.get("rubric_version") != version for row in read_jsonl(output_dir / filename)):
            raise RuntimeError("Study 1 rubric changed; preserve the pilot and use a NEW output directory (e.g. outputs/study1_100_seed42_v6). Old annotations cannot supply the new evidence fields.")


def judge_study1(args: argparse.Namespace) -> tuple[Path, Path]:
    output_dir = Path(args.output_dir)
    _check_study1_output_version(output_dir, args.resume)
    packet_path = Path(args.packet_file) if args.packet_file else output_dir / "packets.jsonl"
    packets = read_jsonl(packet_path)
    if not packets:
        raise RuntimeError(f"No packets found at {packet_path}")
    client, model = _study_client(args)
    output_dir.mkdir(parents=True, exist_ok=True)
    rejudge = set(args.rejudge_session or [])
    packet_ids = {str(packet["session"]["session_id"]) for packet in packets}
    unknown = rejudge - packet_ids
    if unknown:
        raise ValueError(f"rejudge sessions absent from packet file: {sorted(unknown)}")

    requirement_path = output_dir / "requirement_annotations.jsonl"
    fingerprints = {str(packet["session"]["session_id"]): _packet_fingerprint(packet) for packet in packets}
    requirement_rows = _resume_rows(
        requirement_path, packet_ids, lambda row: str(row.get("session_id")),
        rejudge, args.resume, STUDY1_REQUIREMENTS_RUBRIC_VERSION, fingerprints, model,
    )
    requirement_done = {str(row["session_id"]) for row in requirement_rows}
    requirement_mode = "a" if args.resume else "w"
    requirement_errors_path = output_dir / "requirement_errors.jsonl"
    _sync_error_log(
        requirement_errors_path, args.resume, STUDY1_REQUIREMENTS_RUBRIC_VERSION,
        packet_ids, lambda row: str(row.get("session_id")),
    )
    with requirement_path.open(requirement_mode, encoding="utf-8") as results, requirement_errors_path.open(
        requirement_mode, encoding="utf-8"
    ) as errors:
        requirement_jobs = [
            (index, packet) for index, packet in enumerate(packets, 1)
            if str(packet["session"]["session_id"]) not in requirement_done
        ]

        def judge_requirement(job: tuple[int, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
            _, packet = job
            return _complete_validated_json(
                client,
                STUDY1_REQUIREMENTS_SYSTEM_PROMPT,
                study1_requirements_user_prompt(packet_as_text(packet)),
                normalize_study1_requirements,
                lambda value: validate_study1_requirements(
                    value, _packet_turns(packet), _packet_user_turns(packet)
                ),
            )

        for job, completed, error in _run_concurrent_jobs(
            requirement_jobs, judge_requirement, args.workers, args.delay
        ):
            index, packet = job
            session_id = str(packet["session"]["session_id"])
            if error is None:
                annotation, usage = completed
                row = {
                    "session_id": session_id,
                    "repo_id": packet["session"].get("repo_id"),
                    "agent": packet["session"].get("agent"),
                    "observed_costs": packet["session"].get("observed_costs", {}),
                    "turn_timestamps": packet.get("turn_timestamps", {}),
                    "annotation": annotation,
                    "usage": usage,
                    "model": model,
                    "rubric_version": STUDY1_REQUIREMENTS_RUBRIC_VERSION,
                    "input_fingerprint": fingerprints[session_id],
                }
                results.write(json.dumps(row, ensure_ascii=False) + "\n")
                results.flush()
                print(f"[requirements {index}/{len(packets)}] judged {session_id}")
            else:
                errors.write(json.dumps(_failure_record(
                    error, session_id=session_id, model=model, phase="requirements",
                    rubric_version=STUDY1_REQUIREMENTS_RUBRIC_VERSION,
                ), ensure_ascii=False) + "\n")
                errors.flush()
                print(f"[requirements {index}/{len(packets)}] ERROR {session_id}: {error}", file=sys.stderr)

    episode_views = (
        (packet, instruction_turn, prefix_text, valid_turns)
        for packet in packets
        for instruction_turn, prefix_text, valid_turns in iter_behavior_episode_prefixes(packet)
    )
    behavior_path = output_dir / "behavior_annotations.jsonl"
    behavior_keys = {
        f"{packet['session']['session_id']}:T{instruction_turn}"
        for packet in packets for instruction_turn in _packet_user_turns(packet)
    }
    behavior_rows = _resume_rows(
        behavior_path,
        behavior_keys,
        lambda row: f"{row.get('session_id')}:T{row.get('instruction_turn')}",
        rejudge,
        args.resume,
        STUDY1_RUBRIC_VERSION,
        fingerprints,
        model,
    )
    behavior_done = {
        f"{row['session_id']}:T{row['instruction_turn']}" for row in behavior_rows
    }
    behavior_mode = "a" if args.resume else "w"
    behavior_errors_path = output_dir / "behavior_errors.jsonl"
    _sync_error_log(
        behavior_errors_path, args.resume, STUDY1_RUBRIC_VERSION,
        behavior_keys,
        lambda row: f"{row.get('session_id')}:T{row.get('instruction_turn')}",
    )
    with behavior_path.open(behavior_mode, encoding="utf-8") as results, behavior_errors_path.open(
        behavior_mode, encoding="utf-8"
    ) as errors:
        behavior_jobs = (
            (index, packet, instruction_turn, prefix_text, valid_turns)
            for index, (packet, instruction_turn, prefix_text, valid_turns)
            in enumerate(episode_views, 1)
            if f"{packet['session']['session_id']}:T{instruction_turn}" not in behavior_done
        )

        def judge_behavior(
            job: tuple[int, dict[str, Any], int, str, set[int]],
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            _, _, instruction_turn, prefix_text, valid_turns = job
            return _complete_validated_json(
                client,
                STUDY1_BEHAVIOR_SYSTEM_PROMPT,
                study1_behavior_user_prompt(prefix_text, instruction_turn),
                normalize_study1_behavior,
                lambda value: validate_study1_behavior(
                    value, instruction_turn, valid_turns
                ),
            )

        for job, completed, error in _run_concurrent_jobs(
            behavior_jobs, judge_behavior, args.workers, args.delay
        ):
            index, packet, instruction_turn, _, _ = job
            session_id = str(packet["session"]["session_id"])
            key = f"{session_id}:T{instruction_turn}"
            if error is None:
                annotation, usage = completed
                row = {
                    "session_id": session_id,
                    "repo_id": packet["session"].get("repo_id"),
                    "agent": packet["session"].get("agent"),
                    "instruction_turn": instruction_turn,
                    "annotation": annotation,
                    "usage": usage,
                    "model": model,
                    "rubric_version": STUDY1_RUBRIC_VERSION,
                    "input_fingerprint": fingerprints[session_id],
                }
                results.write(json.dumps(row, ensure_ascii=False) + "\n")
                results.flush()
                print(f"[behavior {index}/{len(behavior_keys)}] judged {key}")
            else:
                errors.write(json.dumps(_failure_record(
                    error, session_id=session_id, instruction_turn=instruction_turn, model=model,
                    phase="behavior", rubric_version=STUDY1_RUBRIC_VERSION,
                ), ensure_ascii=False) + "\n")
                errors.flush()
                print(f"[behavior {index}/{len(behavior_keys)}] ERROR {key}: {error}", file=sys.stderr)
    return requirement_path, behavior_path


def _summary_rows(
    output_dir: Path, filename: str, version: str, packets: list[dict[str, Any]],
    episode: bool = False,
) -> list[dict[str, Any]]:
    fingerprints = {str(packet["session"]["session_id"]): _packet_fingerprint(packet) for packet in packets}
    valid_episodes = {
        (str(packet["session"]["session_id"]), turn)
        for packet in packets for turn in _packet_user_turns(packet)
    } if episode else set()
    selected = {}
    for row in read_jsonl(output_dir / filename):
        session_id = str(row.get("session_id"))
        key = (session_id, row.get("instruction_turn")) if episode else session_id
        if row.get("rubric_version") != version:
            continue
        if fingerprints and (session_id not in fingerprints or row.get("input_fingerprint") != fingerprints[session_id]):
            continue
        if episode and packets and key not in valid_episodes:
            continue
        selected[key] = row
    return list(selected.values())


def _study_run_meta(output_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path = output_dir / "prepare_meta.json"
    return {
        "prepare": json.loads(path.read_text(encoding="utf-8")) if path.exists() else {},
        "models": sorted({str(row.get("model", "unknown")) for row in rows}),
        "generated_at_unix": int(time.time()),
    }


def summarize_study1(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    _check_study1_output_version(output_dir, True)
    packets = read_jsonl(output_dir / "packets.jsonl")
    requirement_rows = _summary_rows(output_dir, "requirement_annotations.jsonl", STUDY1_REQUIREMENTS_RUBRIC_VERSION, packets)
    behavior_rows = _summary_rows(output_dir, "behavior_annotations.jsonl", STUDY1_RUBRIC_VERSION, packets, episode=True)
    if not packets and not requirement_rows:
        raise RuntimeError("No packets or requirement annotations found")
    expected = len(packets) if packets else len(requirement_rows)
    expected_episodes = sum(len(_packet_user_turns(packet)) for packet in packets) if packets else len(behavior_rows)
    completed_episodes = {(str(row["session_id"]), row["instruction_turn"]) for row in behavior_rows}
    requirement_ids = {str(row["session_id"]) for row in requirement_rows}
    complete_sessions = sum(
        str(packet["session"]["session_id"]) in requirement_ids and all(
            (str(packet["session"]["session_id"]), turn) in completed_episodes
            for turn in _packet_user_turns(packet)
        ) for packet in packets
    ) if packets else len(requirement_rows)
    summary = aggregate_study1(requirement_rows, behavior_rows)
    summary["run_meta"] = _study_run_meta(output_dir, requirement_rows + behavior_rows)
    summary["run_completeness"] = {
        "requirements_rubric_version": STUDY1_REQUIREMENTS_RUBRIC_VERSION,
        "behavior_rubric_version": STUDY1_RUBRIC_VERSION,
        "packet_session_count": expected,
        "annotated_session_count": complete_sessions,
        "requirement_annotated_session_count": len(requirement_rows),
        "pending_or_failed_session_count": expected - complete_sessions,
        "expected_behavior_episode_count": expected_episodes,
        "annotated_behavior_episode_count": len(behavior_rows),
        "pending_or_failed_behavior_episode_count": expected_episodes - len(behavior_rows),
        "completion_rate": complete_sessions / expected if expected else None,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if complete_sessions < expected:
        print(f"WARNING: Study 1 is incomplete ({complete_sessions}/{expected}); rerun with --resume", file=sys.stderr)
    print(f"Wrote {output_dir / 'summary.json'}")


def judge_study2(args: argparse.Namespace) -> Path:
    output_dir = Path(args.output_dir)
    packet_path = Path(args.packet_file) if args.packet_file else output_dir / "packets.jsonl"
    packets = read_jsonl(packet_path)
    if not packets:
        raise RuntimeError(f"No packets found at {packet_path}")
    client, model = _study_client(args)
    output_dir.mkdir(parents=True, exist_ok=True)
    rejudge = set(args.rejudge_session or [])
    packet_ids = {str(packet["session"]["session_id"]) for packet in packets}
    unknown = rejudge - packet_ids
    if unknown:
        raise ValueError(f"rejudge sessions absent from packet file: {sorted(unknown)}")
    results_path = output_dir / "intent_annotations.jsonl"
    fingerprints = {str(packet["session"]["session_id"]): _packet_fingerprint(packet) for packet in packets}
    existing = _resume_rows(
        results_path, packet_ids, lambda row: str(row.get("session_id")),
        rejudge, args.resume, STUDY2_RUBRIC_VERSION, fingerprints, model,
    )
    done = {str(row["session_id"]) for row in existing}
    mode = "a" if args.resume else "w"
    errors_path = output_dir / "intent_errors.jsonl"
    _sync_error_log(
        errors_path, args.resume, STUDY2_RUBRIC_VERSION,
        packet_ids, lambda row: str(row.get("session_id")),
    )
    with results_path.open(mode, encoding="utf-8") as results, errors_path.open(
        mode, encoding="utf-8"
    ) as errors:
        intent_jobs = [
            (index, packet) for index, packet in enumerate(packets, 1)
            if str(packet["session"]["session_id"]) not in done
        ]

        def judge_intent(job: tuple[int, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
            _, packet = job
            return _complete_validated_json(
                client,
                STUDY2_SYSTEM_PROMPT,
                study2_user_prompt(packet_as_text(packet)),
                normalize_study2_annotation,
                lambda value: validate_study2_annotation(
                    value, _packet_turns(packet), _packet_user_turns(packet)
                ),
            )

        for job, completed, error in _run_concurrent_jobs(
            intent_jobs, judge_intent, args.workers, args.delay
        ):
            index, packet = job
            session_id = str(packet["session"]["session_id"])
            if error is None:
                annotation, usage = completed
                row = {
                    "session_id": session_id,
                    "repo_id": packet["session"].get("repo_id"),
                    "agent": packet["session"].get("agent"),
                    "observed_costs": packet["session"].get("observed_costs", {}),
                    "turn_timestamps": packet.get("turn_timestamps", {}),
                    "annotation": annotation,
                    "usage": usage,
                    "model": model,
                    "rubric_version": STUDY2_RUBRIC_VERSION,
                    "input_fingerprint": fingerprints[session_id],
                }
                results.write(json.dumps(row, ensure_ascii=False) + "\n")
                results.flush()
                print(f"[intent {index}/{len(packets)}] judged {session_id}")
            else:
                errors.write(json.dumps(_failure_record(
                    error, session_id=session_id, model=model, phase="study2",
                    rubric_version=STUDY2_RUBRIC_VERSION,
                ), ensure_ascii=False) + "\n")
                errors.flush()
                print(f"[intent {index}/{len(packets)}] ERROR {session_id}: {error}", file=sys.stderr)
    return results_path


def summarize_study2(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    packets = read_jsonl(output_dir / "packets.jsonl")
    packet_ids = {
        str(packet.get("session", {}).get("session_id")) for packet in packets
        if packet.get("session", {}).get("session_id") is not None
    }
    rows = _summary_rows(output_dir, "intent_annotations.jsonl", STUDY2_RUBRIC_VERSION, packets)
    if not rows and not packets:
        raise RuntimeError("No packets or intent annotations found")
    annotated_ids = {str(row.get("session_id")) for row in rows}
    expected = len(packet_ids) if packet_ids else len(annotated_ids)
    completed = len(annotated_ids & packet_ids) if packet_ids else len(annotated_ids)
    summary = {
        "run_meta": _study_run_meta(output_dir, rows),
        "run_completeness": {
            "rubric_version": STUDY2_RUBRIC_VERSION,
            "packet_session_count": expected,
            "annotated_session_count": completed,
            "pending_or_failed_session_count": max(0, expected - completed),
            "completion_rate": completed / expected if expected else None,
        },
        **aggregate_study2(rows),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if completed < expected:
        print(
            f"WARNING: Study 2 is incomplete ({completed}/{expected}); rerun with --resume",
            file=sys.stderr,
        )
    print(f"Wrote {output_dir / 'summary.json'}")


def summarize(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    rows = read_jsonl(output_dir / "annotations.jsonl")
    if not rows:
        raise RuntimeError("No annotations found")
    prepare_meta_path = output_dir / "prepare_meta.json"
    prepare_meta: dict[str, Any] = {}
    if prepare_meta_path.exists():
        prepare_meta = json.loads(prepare_meta_path.read_text(encoding="utf-8"))
    run_meta = {
        **prepare_meta,
        "model": rows[0].get("model", "unknown"),
        "generated_at_unix": int(time.time()),
    }
    summary = aggregate(rows)
    save_summary(output_dir, summary, run_meta)
    print(f"Wrote {output_dir / 'summary.json'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze evolving project goals in SWE-Chat")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_prepare_options(
        command: argparse.ArgumentParser, *, default_output_dir: str = "outputs/main"
    ) -> None:
        command.add_argument("--data-dir", default="data/swe-chat")
        command.add_argument("--output-dir", default=default_output_dir)
        command.add_argument("--sample-size", type=int, default=200)
        command.add_argument("--seed", type=int, default=42)
        command.add_argument("--min-prompts", type=int, default=2)
        command.add_argument(
            "--max-prompts", type=int, default=50,
            help="Upper prompt-count bound; use 0 for no upper bound",
        )
        command.add_argument("--agent", action="append", help="Repeat to select agents")
        command.add_argument("--max-packet-chars", type=int, default=45_000)
        command.add_argument("--no-commits", action="store_true")

    def add_judge_options(
        command: argparse.ArgumentParser, *, include_output_dir: bool = True,
        default_output_dir: str = "outputs/main", include_workers: bool = False,
    ) -> None:
        if include_output_dir:
            command.add_argument("--output-dir", default=default_output_dir)
        command.add_argument("--packet-file")
        command.add_argument("--env-file", default=".env")
        command.add_argument("--base-url")
        command.add_argument("--api-key")
        command.add_argument("--model")
        command.add_argument("--timeout", type=int, default=180)
        command.add_argument("--max-retries", type=int, default=4)
        command.add_argument("--delay", type=float, default=0)
        if include_workers:
            command.add_argument(
                "--workers", "--concurrency", dest="workers", type=_positive_int, default=1,
                help=("Maximum simultaneous judge requests; repairs stay within the same "
                      "worker (default: 1)"),
            )
        command.add_argument(
            "--rejudge-session", action="append",
            help="Re-run this session even when --resume already has an annotation; repeatable",
        )
        command.add_argument(
            "--trust-env-proxy", action=argparse.BooleanOptionalAction, default=None,
            help="Use HTTP(S)_PROXY from the environment (default: false)",
        )
        command.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)

    prepare_parser = subparsers.add_parser("prepare", help="Sample sessions and create judge packets")
    add_prepare_options(prepare_parser)
    prepare_parser.set_defaults(func=prepare)

    judge_parser = subparsers.add_parser("judge", help="Call an OpenAI-compatible LLM")
    add_judge_options(judge_parser)
    judge_parser.set_defaults(func=judge)

    summary_parser = subparsers.add_parser("summarize", help="Aggregate annotation metrics")
    summary_parser.add_argument("--output-dir", default="outputs/main")
    summary_parser.set_defaults(func=summarize)

    run_parser = subparsers.add_parser("run", help="Prepare, judge, and summarize")
    add_prepare_options(run_parser)
    add_judge_options(run_parser, include_output_dir=False)
    run_parser.set_defaults(func=None)

    study1_judge_parser = subparsers.add_parser(
        "judge-study1", help="Judge requirement emergence and agent behavior"
    )
    add_judge_options(
        study1_judge_parser, default_output_dir="outputs/study1", include_workers=True
    )
    study1_judge_parser.set_defaults(func=judge_study1)

    study1_summary_parser = subparsers.add_parser(
        "summarize-study1", help="Aggregate project-one metrics"
    )
    study1_summary_parser.add_argument("--output-dir", default="outputs/study1")
    study1_summary_parser.set_defaults(func=summarize_study1)

    study1_run_parser = subparsers.add_parser(
        "run-study1", help="Prepare, judge, and summarize project one"
    )
    add_prepare_options(study1_run_parser, default_output_dir="outputs/study1")
    add_judge_options(study1_run_parser, include_output_dir=False, include_workers=True)
    study1_run_parser.set_defaults(func=None)

    study2_judge_parser = subparsers.add_parser(
        "judge-study2", help="Judge user belief and surface-instruction/reality mismatch"
    )
    add_judge_options(
        study2_judge_parser, default_output_dir="outputs/study2", include_workers=True
    )
    study2_judge_parser.set_defaults(func=judge_study2)

    study2_summary_parser = subparsers.add_parser(
        "summarize-study2", help="Aggregate project-two metrics"
    )
    study2_summary_parser.add_argument("--output-dir", default="outputs/study2")
    study2_summary_parser.set_defaults(func=summarize_study2)

    study2_run_parser = subparsers.add_parser(
        "run-study2", help="Prepare, judge, and summarize project two"
    )
    add_prepare_options(study2_run_parser, default_output_dir="outputs/study2")
    add_judge_options(study2_run_parser, include_output_dir=False, include_workers=True)
    study2_run_parser.set_defaults(func=None)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "max_prompts") and args.max_prompts == 0:
        args.max_prompts = None
    try:
        if args.command == "run":
            prepare(args)
            judge(args)
            summarize(args)
        elif args.command == "run-study1":
            _check_study1_output_version(Path(args.output_dir), args.resume)
            prepare(args)
            judge_study1(args)
            summarize_study1(args)
        elif args.command == "run-study2":
            prepare(args)
            judge_study2(args)
            summarize_study2(args)
        else:
            args.func(args)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
