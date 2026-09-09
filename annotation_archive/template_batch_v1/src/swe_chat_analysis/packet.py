from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from .io import parse_json_list


def _clip(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _event_line(event: dict[str, Any]) -> tuple[str, int]:
    number = int(event.get("turn_number") or 0)
    kind = event.get("turn_type") or event.get("role") or "event"
    if kind == "tool_use":
        detail = event.get("file_path") or event.get("command") or event.get("content")
        text = f"tool={event.get('tool_name') or '?'} detail={_clip(detail, 500)}"
    elif kind == "tool_result":
        text = f"tool={event.get('tool_name') or '?'} result={_clip(event.get('content'), 600)}"
    else:
        cap = 2400 if kind in {"user_prompt", "continuation_context"} else 1200
        text = _clip(event.get("content"), cap)
    return f"T{number} {kind}: {text}", number


def compact_event(event: dict[str, Any]) -> dict[str, Any] | None:
    kind = event.get("turn_type")
    if kind not in {"user_prompt", "continuation_context", "assistant_response", "tool_use", "tool_result"}:
        return None
    event = dict(event)
    if kind == "user_prompt" and event.get("is_continuation"):
        event["turn_type"] = "continuation_context"
    cap = 2400 if kind in {"user_prompt", "continuation_context"} else 600 if kind == "tool_result" else 500 if kind == "tool_use" else 1200
    clipped = bool(event.get("text_clipped"))
    for field in ("content", "command", "file_path"):
        if event.get(field) is not None:
            original = " ".join(str(event[field]).split())
            event[field] = _clip(original, cap)
            clipped |= len(original) > cap
    event["text_clipped"] = clipped
    return event


def build_packet(
    session: dict[str, Any],
    events: list[dict[str, Any]],
    commit_map: dict[str, list[dict[str, Any]]] | None = None,
    max_chars: int = 45_000,
) -> dict[str, Any]:
    commit_map = commit_map or {}
    events = [event for source in events if (event := compact_event(source)) is not None]
    duplicate_turns = len({event.get("turn_number") for event in events}) != len(events)
    source_turn_numbers = {
        str(index): event.get("turn_number") for index, event in enumerate(events)
    } if duplicate_turns else {}
    if duplicate_turns:
        events = [{**event, "turn_number": index} for index, event in enumerate(events)]
    user_lines: list[str] = []
    other_entries: list[tuple[int, str, str]] = []
    user_turns: list[int] = []
    dataset_pushback: dict[str, int] = {}
    turn_timestamps: dict[str, str] = {}
    for event in events:
        line, _ = _event_line(event)
        timestamp = event.get("timestamp")
        if timestamp is not None:
            turn_timestamps[str(int(event.get("turn_number") or 0))] = (
                timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
            )
        if event.get("turn_type") == "user_prompt":
            user_lines.append(line)
            user_turns.append(int(event.get("turn_number") or 0))
            label = event.get("prompt_pushback")
            if label:
                dataset_pushback[str(label)] = dataset_pushback.get(str(label), 0) + 1
        elif event.get("turn_type") in {"assistant_response", "tool_use", "tool_result", "continuation_context"}:
            other_entries.append((
                int(event.get("turn_number") or 0), line, str(event.get("turn_type")),
            ))

    checkpoints = parse_json_list(session.get("checkpoint_ids"))
    if not checkpoints and session.get("canonical_checkpoint_pk"):
        checkpoints = [str(session["canonical_checkpoint_pk"])]
    commits = [commit for checkpoint in checkpoints for commit in commit_map.get(checkpoint, [])]
    commits = list({
        str(commit.get("commit_sha") or f"missing-{index}"): commit
        for index, commit in enumerate(commits)
    }.values())
    commit_lines = [
        "commit " + _clip(commit.get("commit_sha"), 10)
        + f": {_clip(commit.get('commit_message'), 300)}; "
        + f"files={commit.get('files_changed_count')}, +{commit.get('total_additions')}/-{commit.get('total_deletions')}; "
        + _clip(commit.get("files_changed"), 500)
        for commit in commits
    ]
    if len(commit_lines) > 8:
        commit_lines = commit_lines[:4] + [f"… {len(commit_lines) - 8} commits omitted …"] + commit_lines[-4:]

    # Keep all prompts for eligible sessions while making the configured budget
    # effective. With the default max_prompts=50 this retains useful text from
    # every turn instead of silently dropping late requirements.
    user_budget = int(max_chars * 0.35)
    prompts_reclipped = len("\n".join(user_lines)) > user_budget
    if len("\n".join(user_lines)) > user_budget and user_lines:
        per_prompt = max(100, user_budget // len(user_lines))
        user_lines = [_clip(line, per_prompt) for line in user_lines]

    human_modified = session.get("human_modified")
    human_removed = session.get("human_removed")
    human_rework_lines = (
        float(human_modified or 0) + float(human_removed or 0)
        if human_modified is not None or human_removed is not None else None
    )
    input_tokens = session.get("input_tokens")
    output_tokens = session.get("output_tokens")
    cache_creation_tokens = session.get("cache_creation_tokens")
    cache_read_tokens = session.get("cache_read_tokens")
    total_tokens = (
        int(input_tokens or 0) + int(output_tokens or 0)
        + int(cache_creation_tokens or 0) + int(cache_read_tokens or 0)
        if any(value is not None for value in (
            input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        )) else None
    )
    observed_costs = {
        "turn_count": session.get("turn_count"),
        "tool_call_count": session.get("tool_call_count"),
        "api_call_count": session.get("api_call_count"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_read_tokens": cache_read_tokens,
        "total_tokens": total_tokens,
        "duration_seconds": session.get("duration_seconds"),
        "human_modified_lines": human_modified,
        "human_removed_lines": human_removed,
        "human_rework_lines": human_rework_lines,
        "agent_lines": session.get("agent_lines"),
        "linked_commit_additions": (
            sum(int(commit.get("total_additions") or 0) for commit in commits) if commits else None
        ),
        "linked_commit_deletions": (
            sum(int(commit.get("total_deletions") or 0) for commit in commits) if commits else None
        ),
        # This is the share of final committed lines attributed to the agent. It
        # is useful as a survival proxy, but is not a longitudinal line-survival measure.
        "committed_agent_code_share": (
            float(session["agent_percentage"]) / 100
            if session.get("agent_percentage") is not None else None
        ),
    }
    header = {
        "session_id": str(session["session_id"]),
        "repo_id": session.get("repo_id"),
        "agent": session.get("agent"),
        "strategy": session.get("strategy"),
        "prompt_count": session.get("prompt_count"),
        "turn_count": session.get("turn_count"),
        "files_touched": parse_json_list(session.get("files_touched"))[:50],
        "agent_percentage": session.get("agent_percentage"),
        "total_committed": session.get("total_committed"),
        "session_success_dataset_label": session.get("session_success"),
        "user_persona_dataset_label": session.get("user_persona"),
        "research_count": session.get("research_count"),
        "action_count": session.get("action_count"),
        "dataset_prompt_pushback_counts": dataset_pushback,
        "observed_costs": observed_costs,
    }

    # Preserve every user prompt. Then select response evidence in rounds so every
    # instruction episode gets coverage before long episodes consume the budget.
    fixed = "\n".join(user_lines + commit_lines)
    budget = max(0, max_chars - len(fixed))
    chosen: list[str] = []
    used = 0
    episode_groups: list[list[int]] = []
    for position, user_turn in enumerate(user_turns):
        next_turn = user_turns[position + 1] if position + 1 < len(user_turns) else float("inf")
        episode_groups.append([
            index for index, (turn, _, _) in enumerate(other_entries)
            if user_turn < turn < next_turn
        ])

    priority_indices: list[int] = []
    # First and last assistant response in every episode are strongest evidence
    # for clarification and task-model updates.
    for take_last in (False, True):
        for group in episode_groups:
            assistant = [i for i in group if other_entries[i][2] == "assistant_response"]
            if assistant:
                priority_indices.append(assistant[-1] if take_last else assistant[0])
    # Give every episode representative project/execution evidence.
    for take_last in (False, True):
        for group in episode_groups:
            tools = [i for i in group if other_entries[i][2] in {"tool_use", "tool_result"}]
            if tools:
                priority_indices.append(tools[-1] if take_last else tools[0])
    # Promote failures and tests because they can expose project constraints.
    for index, (_, line, kind) in enumerate(other_entries):
        lowered = line.lower()
        if kind == "tool_result" and any(token in lowered for token in (
            "error", "fail", "exception", "test", "warning", "conflict",
        )):
            priority_indices.append(index)
    # Fill any remaining space from both ends of the trace.
    priority_indices.extend(range(len(other_entries)))
    priority_indices.extend(reversed(range(len(other_entries))))

    selected_indices: set[int] = set()
    for index in priority_indices:
        if index in selected_indices:
            continue
        candidate = other_entries[index][1]
        if used + len(candidate) + 1 <= budget:
            selected_indices.add(index)
            used += len(candidate) + 1
    chosen = [other_entries[index][1] for index in sorted(selected_indices)]
    # Restore chronological order using the T<number> prefix.
    chosen.sort(key=lambda line: int(line.split(" ", 1)[0][1:]))

    transcript = "\n".join(user_lines + chosen)
    # Sorting again interleaves user and execution events correctly.
    transcript_lines = transcript.splitlines()
    transcript_lines.sort(key=lambda line: int(line.split(" ", 1)[0][1:]))
    return {
        "session": header,
        "transcript": "\n".join(transcript_lines),
        "commits": commit_lines,
        "packet_truncated": len(chosen) < len(other_entries) or prompts_reclipped or len(commits) > 8 or any(event.get("text_clipped") for event in events),
        "packet_selection_strategy": "episode_aware_v2",
        "packet_diagnostics": {
            "source_event_count": len(events),
            "retained_event_count": len(transcript_lines),
            "text_clipped_event_count": sum(bool(event.get("text_clipped")) for event in events),
            "user_prompts_reclipped": prompts_reclipped,
            "actual_user_prompt_count": len(user_turns),
            "turn_numbers_reindexed": duplicate_turns,
            "source_turn_numbers": source_turn_numbers,
            "transcript_chars": len("\n".join(transcript_lines)),
            "max_packet_chars": max_chars,
        },
        "turn_timestamps": turn_timestamps,
    }


def packet_as_text(packet: dict[str, Any]) -> str:
    # Keep published SWE-Chat LLM labels in packets/results for validation, but
    # blind our judge to them to avoid circular annotation.
    blinded_session = {
        key: value for key, value in packet["session"].items()
        if key in {"session_id", "repo_id", "agent", "strategy"}
    }
    return (
        "SESSION METADATA\n"
        + json.dumps(blinded_session, ensure_ascii=False, default=str, indent=2)
        + "\n\nORDERED SESSION EVENTS\n"
        + packet["transcript"]
        + "\n\nLINKED COMMIT EVIDENCE\n"
        + ("\n".join(packet["commits"]) if packet["commits"] else "No linked commit evidence supplied.")
        + f"\n\nPACKET_TRUNCATED={packet['packet_truncated']}"
    )


def iter_behavior_episode_prefixes(packet: dict[str, Any]) -> Iterator[tuple[int, str, set[int]]]:
    """Build one no-future-information view for every user instruction turn."""
    lines = packet.get("transcript", "").splitlines()
    numbered: list[tuple[int, str]] = []
    user_turns: list[int] = []
    for line in lines:
        if not line.startswith("T") or " " not in line:
            continue
        prefix = line.split(" ", 1)[0]
        try:
            turn = int(prefix[1:])
        except ValueError:
            continue
        numbered.append((turn, line))
        if line.startswith(f"T{turn} user_prompt:"):
            user_turns.append(turn)

    static_session = {
        key: packet.get("session", {}).get(key)
        for key in ("session_id", "repo_id", "agent", "strategy")
    }
    for index, instruction_turn in enumerate(user_turns):
        next_turn = user_turns[index + 1] if index + 1 < len(user_turns) else float("inf")
        prefix_lines = [line for turn, line in numbered if turn < next_turn]
        valid_turns = {turn for turn, _ in numbered if turn < next_turn}
        text = (
            "STATIC SESSION METADATA\n"
            + json.dumps(static_session, ensure_ascii=False, default=str, indent=2)
            + "\n\nEVENTS AVAILABLE THROUGH THIS EPISODE\n"
            + "\n".join(prefix_lines)
            + f"\n\nSOURCE_PACKET_TRUNCATED={packet.get('packet_truncated', False)}"
        )
        yield instruction_turn, text, valid_turns


def behavior_episode_prefixes(packet: dict[str, Any]) -> list[tuple[int, str, set[int]]]:
    return list(iter_behavior_episode_prefixes(packet))
