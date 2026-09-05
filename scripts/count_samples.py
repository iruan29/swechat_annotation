#!/usr/bin/env python3
"""Count the local study population and nominal judge jobs without API calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from swe_chat_analysis.io import read_user_prompt_counts, sample_sessions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/swe-chat"))
    parser.add_argument("--sample-size", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-prompts", type=int, default=2)
    parser.add_argument("--max-prompts", type=int, default=0)
    parser.add_argument("--agent", action="append")
    args = parser.parse_args()
    if args.sample_size < 0 or args.min_prompts < 1 or args.max_prompts < 0:
        parser.error("Require sample-size >= 0, min-prompts >= 1, and max-prompts >= 0")
    if args.max_prompts and args.max_prompts < args.min_prompts:
        parser.error("max-prompts must be 0 or >= min-prompts")
    counts = read_user_prompt_counts(args.data_dir / "conversations.parquet")
    options = (args.data_dir / "sessions.parquet", args.sample_size, args.seed,
               args.min_prompts, args.max_prompts or None, set(args.agent) if args.agent else None)
    selected = sample_sessions(*options, prompt_counts=counts)
    episodes = sum(counts[str(row["session_id"])] for row in selected)
    print(json.dumps({
        "dataset_session_count": pq.ParquetFile(args.data_dir / "sessions.parquet").metadata.num_rows,
        "metadata_eligible_session_count": len(sample_sessions(options[0], 0, *options[2:])),
        "selected_session_count": len(selected),
        "study1_requirement_jobs": len(selected),
        "study1_behavior_jobs": episodes,
        "study1_total_jobs_before_retries": len(selected) + episodes,
        "study2_total_jobs_before_retries": len(selected),
        "note": "Metadata prompt bounds plus observed non-continuation prompt minimum; tasks/requirements are judge-derived, not samples.",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
