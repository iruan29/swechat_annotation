#!/usr/bin/env python3
"""Create a tiny local dataset for smoke tests; never use it for conclusions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/fixture")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    sessions = [{
        "session_id": "fixture-1", "repo_id": "example/project",
        "checkpoint_ids": json.dumps(["example/project#abc"]),
        "canonical_checkpoint_pk": "example/project#abc", "agent": "Fixture Agent",
        "strategy": "auto", "files_touched": json.dumps(["app.py", "test_app.py"]),
        "files_touched_count": 2, "agent_percentage": 100.0, "turn_count": 6,
        "prompt_count": 3, "user_persona": "Mind Changer", "session_success": "90",
        "research_count": 2, "action_count": 3, "total_committed": 20.0,
    }]
    defaults = {
        "conversation_turn_number": None, "content": None, "tool_name": None,
        "file_path": None, "command": None, "category": None,
        "prompt_intent": None, "prompt_pushback": None,
    }
    conversations = [
        {**defaults, "session_id": "fixture-1", "turn_number": 0, "conversation_turn_number": 0, "role": "user", "turn_type": "user_prompt", "content": "Add CSV export.", "prompt_intent": "create new code", "prompt_pushback": "non_pushback"},
        {**defaults, "session_id": "fixture-1", "turn_number": 1, "role": "tool_use", "turn_type": "tool_use", "tool_name": "Read", "file_path": "app.py", "category": "Research"},
        {**defaults, "session_id": "fixture-1", "turn_number": 2, "role": "assistant", "turn_type": "assistant_response", "content": "The existing exporter is async. Should CSV use the same job queue?"},
        {**defaults, "session_id": "fixture-1", "turn_number": 3, "conversation_turn_number": 2, "role": "user", "turn_type": "user_prompt", "content": "Yes, and it must stream rows to avoid memory spikes.", "prompt_intent": "create new code", "prompt_pushback": "requirement_change"},
        {**defaults, "session_id": "fixture-1", "turn_number": 4, "role": "tool_result", "turn_type": "tool_result", "tool_name": "Bash", "content": "Test failed: exported columns don't preserve configured ordering."},
        {**defaults, "session_id": "fixture-1", "turn_number": 5, "conversation_turn_number": 4, "role": "user", "turn_type": "user_prompt", "content": "Preserve configured column order too.", "prompt_intent": "test", "prompt_pushback": "correction"},
    ]
    commits = [{
        "checkpoint_pk": "example/project#abc", "commit_sha": "a" * 40,
        "commit_message": "Add streaming CSV export with stable column order",
        "files_changed_count": 2, "total_additions": 18, "total_deletions": 2,
        "files_changed": "M app.py\nA test_app.py", "status": "ok",
    }]
    pq.write_table(pa.Table.from_pylist(sessions), output / "sessions.parquet")
    pq.write_table(pa.Table.from_pylist(conversations), output / "conversations.parquet")
    pq.write_table(pa.Table.from_pylist(commits), output / "commits.parquet")
    print(f"Fixture written to {output}")


if __name__ == "__main__":
    main()
