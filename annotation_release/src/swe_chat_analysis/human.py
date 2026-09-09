from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import itertools
import json
from pathlib import Path
import random
import re
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import human_simple
from .human_schema import STAGES, VERSIONS, PROMPTS, blank, schema, validate
from .io import parse_json_list, read_commit_summaries, read_conversations, read_jsonl, read_user_prompt_counts, sample_sessions, write_jsonl
from .packet import build_packet
from .study1 import aggregate_study1
from .study2 import aggregate_study2


HUMAN_VERSION = "human_full_trace_v1"
ASSETS = Path(__file__).parent / "human_web"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def make_case(session: dict[str, Any], events: list[dict[str, Any]], commits: dict[str, Any], seed: int) -> dict[str, Any]:
    source_events = list(events)
    source_counts = Counter(str(event.get("turn_type") or "unknown") for event in source_events)
    events = sorted((event for event in source_events if event.get("turn_type") in {
        "user_prompt", "assistant_response", "tool_use", "tool_result",
    }), key=lambda event: int(event.get("turn_number") or 0))
    packet = build_packet(session, events, commits)
    reindexed = packet["packet_diagnostics"]["turn_numbers_reindexed"]
    visible = []
    for index, event in enumerate(events):
        source_turn = int(event.get("turn_number") or 0)
        kind = event["turn_type"]
        if kind == "user_prompt" and event.get("is_continuation"):
            kind = "continuation_context"
        text = str(event.get("content") or "")
        if kind in {"tool_use", "tool_result"}:
            context = "\n".join(f"{key}: {event[key]}" for key in ("tool_name", "file_path", "command") if event.get(key))
            text = context + "\n" + text
        visible.append({"turn": index if reindexed else source_turn, "source_turn": source_turn, "kind": kind, "text": text})
    user_turns = [event["turn"] for event in visible if event["kind"] == "user_prompt"]
    if not user_turns:
        raise ValueError("No non-continuation user instruction")
    target = random.Random(f"{seed}:{session['session_id']}").choice(user_turns)
    case = {
        "case_id": str(session["session_id"]), "repo_id": session.get("repo_id"), "agent": session.get("agent"),
        "target_instruction_turn": target, "user_turns": user_turns, "events": visible,
        "observed_costs": packet["session"]["observed_costs"], "turn_timestamps": packet["turn_timestamps"],
        "trace_scope": {"source_event_count": len(source_events), "source_event_types": dict(source_counts),
                        "included_event_count": len(visible), "excluded_event_count": len(source_events) - len(visible),
                        "selection": "all rows of selected event types from the source session; no prefix or text clipping",
                        "project_start_to_finish_verified": False},
        "commits": packet["commits"], "source": "conversations.parquet_unclipped_selected_event_types",
    }
    case["input_fingerprint"] = digest(case)
    return case


def prepare(args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("人工项目目录必须为空：不能覆盖已冻结样本或标注，请指定新目录")
    data = Path(args.data_dir)
    if args.sample_size < 1 or args.min_prompts < 1 or args.max_prompts < 0 or args.max_prompts and args.max_prompts < args.min_prompts:
        raise ValueError("sample-size/min-prompts 必须为正数；max-prompts 为 0 或不小于 min-prompts")
    counts = read_user_prompt_counts(data / "conversations.parquet")
    sessions = sample_sessions(data / "sessions.parquet", args.sample_size, args.seed,
                               args.min_prompts, args.max_prompts or None, prompt_counts=counts)
    if not sessions:
        raise ValueError("没有符合条件的 session")
    events = read_conversations(data / "conversations.parquet", [str(row["session_id"]) for row in sessions])
    checkpoints = {checkpoint for row in sessions for checkpoint in (
        parse_json_list(row.get("checkpoint_ids")) or [str(row.get("canonical_checkpoint_pk") or "")]) if checkpoint}
    commits = read_commit_summaries(data / "commits.parquet", checkpoints)
    cases = [make_case(row, events.pop(str(row["session_id"]), []), commits, args.seed) for row in sessions]
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "cases.jsonl", cases)
    manifest = {
        "human_version": HUMAN_VERSION, "rubric_versions": VERSIONS, "seed": args.seed,
        "sample_size_requested": args.sample_size, "session_count": len(cases),
        "min_prompts": args.min_prompts, "max_prompts": args.max_prompts,
        "sampling": "uniform sessions after metadata bounds and observed non-continuation minimum; one uniform user episode per session",
        "behavior_episode_count": len(cases), "created_at_unix": int(time.time()),
        "case_fingerprints": {case["case_id"]: case["input_fingerprint"] for case in cases},
        "source_files": {name: {"bytes": (data / name).stat().st_size, "mtime_ns": (data / name).stat().st_mtime_ns}
                         for name in ("sessions.parquet", "conversations.parquet", "commits.parquet") if (data / name).exists()},
        "commits_included": (data / "commits.parquet").exists(),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已冻结 {len(cases)} 个 session；每位标注员有 {len(cases) * 3} 个阶段。无模型 API 调用。目录：{output}")


class Conflict(ValueError):
    pass


class HumanProject:
    def __init__(self, output: Path):
        self.output = output
        self.manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.simple = self.manifest.get("human_version") == human_simple.VERSION
        self.stages = (human_simple.STAGE,) if self.simple else STAGES
        self.versions = {human_simple.STAGE: human_simple.VERSION} if self.simple else VERSIONS
        if self.manifest.get("human_version") not in {HUMAN_VERSION, human_simple.VERSION} or self.manifest.get("rubric_versions") != self.versions:
            raise ValueError("项目版本与当前代码不匹配；请保留旧项目并使用匹配版本，不静默迁移")
        rows = read_jsonl(output / "cases.jsonl")
        self.cases = {row["case_id"]: row for row in rows}
        if len(self.cases) != len(rows) or len(rows) != self.manifest["session_count"]:
            raise ValueError("样本数量或唯一性检查失败")
        for case in rows:
            fingerprint = digest({key: value for key, value in case.items() if key != "input_fingerprint"})
            if fingerprint != case["input_fingerprint"] or self.manifest["case_fingerprints"].get(case["case_id"]) != fingerprint:
                raise ValueError("冻结样本已变更，拒绝混用标注")
        self.database = output / "human.sqlite3"
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS annotations (
                    annotator TEXT NOT NULL, case_id TEXT NOT NULL, stage TEXT NOT NULL,
                    revision INTEGER NOT NULL, status TEXT NOT NULL, raw_json TEXT NOT NULL,
                    normalized_json TEXT, updated REAL NOT NULL,
                    PRIMARY KEY (annotator, case_id, stage));
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY, annotator TEXT NOT NULL, case_id TEXT NOT NULL,
                    stage TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL,
                    raw_json TEXT NOT NULL, normalized_json TEXT, updated REAL NOT NULL);
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def check_identity(self, annotator: str, case_id: str | None = None, stage: str | None = None) -> None:
        assigned = self.manifest.get("assigned_annotator")
        if assigned and annotator != assigned:
            raise ValueError(f"本份任务固定属于 {assigned}，不能切换到其他标注员")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", annotator):
            raise ValueError("标注员 ID 只允许 1–64 位字母、数字、下划线或连字符")
        if case_id is not None and case_id not in self.cases:
            raise ValueError("未知样本")
        if stage is not None and stage not in self.stages:
            raise ValueError("未知阶段")

    def rows(self, annotator: str) -> list[dict[str, Any]]:
        self.check_identity(annotator)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM annotations WHERE annotator=?", (annotator,))]

    def accessible(self, connection: sqlite3.Connection, annotator: str, case_id: str, stage: str) -> None:
        for earlier in self.stages[:self.stages.index(stage)]:
            result = connection.execute("SELECT status FROM annotations WHERE annotator=? AND case_id=? AND stage=?", (annotator, case_id, earlier)).fetchone()
            if result is None or result["status"] != "complete":
                raise Conflict("必须先提交前一阶段；行为阶段未完成时不能读取未来消息")

    def visible_events(self, case_id: str, stage: str) -> list[dict[str, Any]]:
        case = self.cases[case_id]
        if stage != "behavior":
            return case["events"]
        following = [turn for turn in case["user_turns"] if turn > case["target_instruction_turn"]]
        boundary = min(following) if following else float("inf")
        return [event for event in case["events"] if event["turn"] < boundary]

    def case_view(self, annotator: str, case_id: str, stage: str) -> dict[str, Any]:
        self.check_identity(annotator, case_id, stage)
        with self.connect() as connection:
            self.accessible(connection, annotator, case_id, stage)
            saved = connection.execute("SELECT * FROM annotations WHERE annotator=? AND case_id=? AND stage=?", (annotator, case_id, stage)).fetchone()
        spec = human_simple.schema() if self.simple else schema(stage)
        value = json.loads(saved["raw_json"]) if saved else blank(spec)
        if stage == "behavior":
            value["instruction_turn"] = self.cases[case_id]["target_instruction_turn"]
        return {
            "case_id": case_id, "stage": stage, "target_instruction_turn": self.cases[case_id]["target_instruction_turn"],
            "schema": spec, "annotation": value, "revision": saved["revision"] if saved else 0,
            "status": saved["status"] if saved else "new", "events": self.visible_events(case_id, stage),
            "commits": [] if stage == "behavior" else self.cases[case_id]["commits"],
            "rubric": human_simple.RUBRIC if self.simple else PROMPTS[stage], "rubric_version": self.versions[stage],
            "interaction_quality": self.cases[case_id].get("interaction_quality"),
            "simple": self.simple, "reading_stats": self.cases[case_id].get("reading_stats"),
            "trace_scope": self.cases[case_id].get("trace_scope") if stage != "behavior" else None,
        }

    def save(self, annotator: str, case_id: str, stage: str, revision: int, raw: dict[str, Any], complete: bool) -> dict[str, Any]:
        self.check_identity(annotator, case_id, stage)
        if not isinstance(raw, dict) or type(revision) is not int or type(complete) is not bool:
            raise ValueError("非法标注结构")
        raw_json = json.dumps(raw, ensure_ascii=False, allow_nan=False)
        status = "complete" if complete else "draft"
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.accessible(connection, annotator, case_id, stage)
            previous = connection.execute("SELECT revision,status FROM annotations WHERE annotator=? AND case_id=? AND stage=?", (annotator, case_id, stage)).fetchone()
            if previous and previous["status"] == "complete" and not self.simple:
                raise Conflict("已提交阶段锁定，不能在看过后续证据后改写；复标/仲裁请使用独立标注员 ID")
            if revision != (previous["revision"] if previous else 0):
                raise Conflict("版本冲突：可能有另一浏览器已保存，请刷新后重试")
            normalized = (human_simple.validate(raw, self.visible_events(case_id, stage)) if self.simple else validate(stage, raw, self.visible_events(case_id, stage), self.cases[case_id]["target_instruction_turn"])) if complete else None
            normalized_json = json.dumps(normalized, ensure_ascii=False, allow_nan=False) if normalized else None
            values = (annotator, case_id, stage, revision + 1, status, raw_json, normalized_json, time.time())
            connection.execute("INSERT OR REPLACE INTO annotations VALUES (?,?,?,?,?,?,?,?)", values)
            connection.execute("INSERT INTO history (annotator,case_id,stage,revision,status,raw_json,normalized_json,updated) VALUES (?,?,?,?,?,?,?,?)", values)
        return {"revision": revision + 1, "status": status, "normalized": normalized}

    def task_list(self, annotator: str) -> dict[str, Any]:
        rows = {(row["case_id"], row["stage"]): row for row in self.rows(annotator)}
        cases = [{"case_id": case_id, "statuses": {stage: rows.get((case_id, stage), {}).get("status", "new") for stage in self.stages}} for case_id in self.cases]
        return {"cases": cases, "total": len(cases), "completed_stages": sum(row["status"] == "complete" for row in rows.values()), "human_version": self.manifest["human_version"], "stages": list(self.stages)}

    def export(self, annotator: str) -> dict[str, Any]:
        completed = [row for row in self.rows(annotator) if row["status"] == "complete"]
        groups: dict[str, list[dict[str, Any]]] = {stage: [] for stage in self.stages}
        for saved in completed:
            case = self.cases[saved["case_id"]]
            row = {
                "session_id": saved["case_id"], "repo_id": case["repo_id"], "agent": case["agent"],
                "annotator": annotator, "annotation_source": "human", "rubric_version": self.versions[saved["stage"]],
                "input_fingerprint": case["input_fingerprint"], "annotation": json.loads(saved["normalized_json"]),
                "raw_annotation": json.loads(saved["raw_json"]), "revision": saved["revision"],
                "observed_costs": case["observed_costs"], "turn_timestamps": case["turn_timestamps"],
            }
            if saved["stage"] == "behavior":
                row["instruction_turn"] = case["target_instruction_turn"]
            if self.simple:
                row["metrics"] = human_simple.costs(case, row["annotation"])
            groups[saved["stage"]].append(row)
        if self.simple:
            return {"delivery": {"format": "swe_chat_delivery_v1", "package_id": self.manifest.get("package_id"),
                    "assignment_id": self.manifest.get("assigned_annotator", annotator),
                    "expected_count": len(self.cases), "completed_count": len(completed),
                    "complete": len(completed) == len(self.cases),
                    "missing_case_ids": sorted(set(self.cases) - {row["case_id"] for row in completed})},
                    "summary": {"human_version": human_simple.VERSION, "annotator": annotator,
                    "run_completeness": {"session_count": len(self.cases), "completed": len(completed)},
                    **human_simple.summarize(groups[human_simple.STAGE])}, "annotations": groups}
        summary = {
            "human_version": HUMAN_VERSION, "annotator": annotator,
            "run_completeness": {"session_count": len(self.cases), "completed_by_stage": {stage: len(rows) for stage, rows in groups.items()},
                                 "fully_completed_session_count": len(set.intersection(*({row["session_id"] for row in rows} for rows in groups.values())))},
            "behavior_sampling": "One uniformly sampled user episode per uniformly sampled session; NOT the all-episodes population. No outcome-based filtering.",
            "study1": aggregate_study1(groups["requirements"], groups["behavior"]),
            "study2": aggregate_study2(groups["study2"]),
        }
        return {"summary": summary, "annotations": groups}

    def agreement(self) -> dict[str, Any]:
        if self.simple:
            return {"supported": False, "reason": "简洁版尚未实现复标一致性统计；需要同一批样本的独立重复标注", "pairs": []}
        with self.connect() as connection:
            rows = connection.execute("SELECT annotator,case_id,normalized_json FROM annotations WHERE stage='behavior' AND status='complete'").fetchall()
        labels: dict[str, dict[str, str]] = {}
        for row in rows:
            labels.setdefault(row["annotator"], {})[row["case_id"]] = json.loads(row["normalized_json"])["behavior_mode"]
        pairs = []
        for left, right in itertools.combinations(sorted(labels), 2):
            shared = sorted(set(labels[left]) & set(labels[right]))
            known = [key for key in shared if labels[left][key] != "unclear" and labels[right][key] != "unclear"]
            agreement = sum(labels[left][key] == labels[right][key] for key in known) / len(known) if known else None
            left_counts = Counter(labels[left][key] for key in known)
            right_counts = Counter(labels[right][key] for key in known)
            chance = sum(count * right_counts[label] for label, count in left_counts.items()) / len(known) ** 2 if known else 1
            pairs.append({"annotators": [left, right], "paired_case_count": len(shared), "classifiable_pair_count": len(known),
                          "excluded_unclear_pair_count": len(shared) - len(known), "agreement": agreement,
                          "cohen_kappa": (agreement - chance) / (1 - chance) if known and chance < 1 else None,
                          "disagreement_case_ids": [key for key in known if labels[left][key] != labels[right][key]]})
        return {"unit": "same sampled behavior episode; unweighted Cohen kappa; not task-thread alignment", "pairs": pairs}


def handler(project: HumanProject, token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def respond(self, status: int, value: Any, mime: str = "application/json; charset=utf-8") -> None:
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() if mime.startswith("application/json") else value
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; object-src 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self) -> bool:
            return secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "application/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in assets:
                filename, mime = assets[path]
                self.respond(200, (ASSETS / filename).read_bytes(), mime)
                return
            if not self.authorized():
                self.respond(401, {"error": "需要启动时 URL 中的访问 token"})
                return
            query = parse_qs(urlsplit(self.path).query)
            try:
                annotator = query.get("annotator", [""])[0]
                if path == "/api/config":
                    result = {"assigned_annotator": project.manifest.get("assigned_annotator"), "package_id": project.manifest.get("package_id")}
                elif path == "/api/tasks":
                    result = project.task_list(annotator)
                elif path == "/api/case":
                    result = project.case_view(annotator, query.get("case_id", [""])[0], query.get("stage", [""])[0])
                elif path == "/api/export":
                    result = project.export(annotator)
                else:
                    self.respond(404, {"error": "Not found"})
                    return
                self.respond(200, result)
            except Conflict as error:
                self.respond(409, {"error": str(error)})
            except (ValueError, KeyError, TypeError) as error:
                self.respond(400, {"error": str(error)})

        def do_POST(self) -> None:
            if not self.authorized():
                self.respond(401, {"error": "Unauthorized"})
                return
            if self.path != "/api/save":
                self.respond(404, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2_000_000:
                    raise ValueError("提交内容须小于 2 MB")
                payload = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非有限数值")))
                result = project.save(payload["annotator"], payload["case_id"], payload["stage"], payload["revision"], payload["annotation"], payload["complete"])
                self.respond(200, result)
            except Conflict as error:
                self.respond(409, {"error": str(error)})
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                self.respond(400, {"error": str(error)})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-Chat 人工标注：规则准备、独立标注、指标导出；不调用 LLM")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--data-dir", default="data/swe-chat")
    prepare_parser.add_argument("--output-dir", default="outputs/human_zh_en_v3_100_seed42")
    prepare_parser.add_argument("--sample-size", type=int, default=100)
    prepare_parser.add_argument("--seed", type=int, default=42)
    prepare_parser.add_argument("--min-prompts", type=int, default=8)
    prepare_parser.add_argument("--max-prompts", type=int, default=0, help="有效交互数上限；0 表示不限")
    prepare_parser.add_argument("--min-chars", type=int, default=1000)
    prepare_parser.add_argument("--max-chars", type=int, default=180000)
    prepare_parser.add_argument("--max-events", type=int, default=600)
    prepare_parser.set_defaults(language_filter=True)
    prepare_parser.add_argument("--legacy", action="store_true", help="使用旧三阶段表单")
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--output-dir", default="outputs/human_zh_en_v3_100_seed42")
    serve_parser.add_argument("--port", type=int, default=8765)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--output-dir", default="outputs/human_zh_en_v3_100_seed42")
    export_parser.add_argument("--annotator", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if args.legacy:
                prepare(args)
            else:
                from .human_sampling import prepare as prepare_simple
                prepare_simple(args)
            return
        project = HumanProject(Path(args.output_dir))
        if args.command == "export":
            result = project.export(args.annotator)
            destination = Path(args.output_dir) / "exports" / args.annotator
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "summary.json").write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
            for stage, rows in result["annotations"].items():
                write_jsonl(destination / f"{stage}_annotations.jsonl", rows)
            (destination / "agreement.json").write_text(json.dumps(project.agreement(), ensure_ascii=False, indent=2), encoding="utf-8")
            if project.simple:
                import csv
                rows = result["annotations"][human_simple.STAGE]
                with (destination / "analysis.csv").open("w", encoding="utf-8-sig", newline="") as file:
                    fields = ["session_id", "agent", "initial_coverage", "new_requirements", "requirement_source", "gap_driver", "instruction_quality", "literal_feasibility"] + list(human_simple.costs(next(iter(project.cases.values())), {"evolution": {"new_requirements": "没有", "first_new_turn": None}}))
                    writer = csv.DictWriter(file, fieldnames=fields)
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({"session_id": row["session_id"], "agent": row["agent"], "initial_coverage": row["annotation"]["evolution"]["initial_coverage"], "new_requirements": row["annotation"]["evolution"]["new_requirements"], "requirement_source": row["annotation"]["evolution"]["source"], "gap_driver": row["annotation"]["gap"]["driver"], "instruction_quality": row["annotation"]["gap"]["instruction_quality"], "literal_feasibility": row["annotation"]["gap"]["literal_feasibility"], **row["metrics"]})
            print(f"已导出至 {destination}；只统计已提交结果，不混入草稿或合并不同标注员")
        else:
            token = secrets.token_urlsafe(32)
            server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(project, token))
            print(f"打开 http://127.0.0.1:{server.server_port}/#token={token}", flush=True)
            print("仅供本机/SSH 隧道内可信标注员使用；不要暴露公网。Ctrl+C 停止。", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
