from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


SESSION_COLUMNS = [
    "session_id", "repo_id", "checkpoint_ids", "canonical_checkpoint_pk",
    "agent", "strategy", "files_touched", "files_touched_count",
    "agent_percentage", "turn_count", "prompt_count", "user_persona",
    "session_success", "research_count", "action_count", "total_committed",
    "input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens",
    "api_call_count", "tool_call_count", "unique_tools_count", "duration_seconds",
    "agent_lines", "human_added", "human_modified", "human_removed",
]
CONVERSATION_COLUMNS = [
    "session_id", "turn_number", "conversation_turn_number", "role",
    "turn_type", "content", "tool_name", "file_path", "command",
    "category", "prompt_intent", "prompt_pushback", "timestamp",
    "input_tokens", "output_tokens", "cache_creation_input_tokens",
    "cache_read_input_tokens",
]


def _available_columns(path: Path, wanted: list[str]) -> list[str]:
    names = set(pq.ParquetFile(path).schema_arrow.names)
    return [column for column in wanted if column in names]


def _python_rows(table: pa.Table) -> list[dict[str, Any]]:
    return table.to_pylist()


def sample_sessions(
    sessions_path: Path,
    sample_size: int,
    seed: int,
    min_prompts: int = 2,
    max_prompts: int | None = 50,
    agents: set[str] | None = None,
) -> list[dict[str, Any]]:
    columns = _available_columns(sessions_path, SESSION_COLUMNS)
    rows = _python_rows(pq.read_table(sessions_path, columns=columns))
    eligible = [
        row for row in rows
        if int(row.get("prompt_count") or 0) >= min_prompts
        and (max_prompts is None or int(row.get("prompt_count") or 0) <= max_prompts)
        and (not agents or row.get("agent") in agents)
    ]
    # Stable seed and ordering make sample membership reproducible.
    eligible.sort(key=lambda row: str(row["session_id"]))
    rng = random.Random(seed)
    if sample_size <= 0 or sample_size >= len(eligible):
        rng.shuffle(eligible)
        return eligible
    return rng.sample(eligible, sample_size)


def read_conversations(
    conversations_path: Path, session_ids: Iterable[str]
) -> dict[str, list[dict[str, Any]]]:
    selected = set(session_ids)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    columns = _available_columns(conversations_path, CONVERSATION_COLUMNS)
    parquet = pq.ParquetFile(conversations_path)
    selected_array = pa.array(sorted(selected), type=pa.string())
    for batch in parquet.iter_batches(batch_size=65_536, columns=columns):
        if "session_id" not in batch.schema.names:
            raise ValueError("conversations.parquet lacks session_id")
        mask = pc.is_in(batch.column("session_id"), value_set=selected_array)
        for row in pa.Table.from_batches([batch]).filter(mask).to_pylist():
            grouped[str(row["session_id"])].append(row)
    for events in grouped.values():
        events.sort(key=lambda row: int(row.get("turn_number") or 0))
    return dict(grouped)


def read_commit_summaries(
    commits_path: Path, checkpoint_ids: set[str]
) -> dict[str, list[dict[str, Any]]]:
    if not commits_path.exists() or not checkpoint_ids:
        return {}
    wanted = [
        "checkpoint_pk", "commit_sha", "commit_message", "files_changed_count",
        "total_additions", "total_deletions", "files_changed", "status",
    ]
    columns = _available_columns(commits_path, wanted)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected_array = pa.array(sorted(checkpoint_ids), type=pa.string())
    for batch in pq.ParquetFile(commits_path).iter_batches(
        batch_size=16_384, columns=columns
    ):
        mask = pc.is_in(batch.column("checkpoint_pk"), value_set=selected_array)
        for row in pa.Table.from_batches([batch]).filter(mask).to_pylist():
            # Deliberately omit full patches: the judge gets outcome metadata without
            # sending large or potentially sensitive code blobs to the API.
            grouped[str(row["checkpoint_pk"])].append(row)
    return dict(grouped)


def parse_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(value)
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows
