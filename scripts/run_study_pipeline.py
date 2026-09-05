#!/usr/bin/env python3
"""Shared download, preparation, annotation, and completeness checks for both studies."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)


def _data_ready(data_dir: Path, include_commits: bool = True) -> bool:
    names = ["sessions.parquet", "conversations.parquet"]
    if include_commits:
        names.append("commits.parquet")
    return all(
        path.is_file() and path.stat().st_size > 0
        for path in (data_dir / name for name in names)
    )


def build_parser(default_study: int = 2) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reproducible SWE-Chat Study 1/2 pipeline: download, sample/process, "
            "judge with resume, and aggregate results"
        )
    )
    parser.add_argument("--study", type=int, choices=(1, 2), default=default_study)
    parser.add_argument("--data-dir", default="data/swe-chat")
    parser.add_argument("--output-dir")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-prompts", type=int, default=2)
    parser.add_argument("--max-prompts", type=int, default=50)
    parser.add_argument("--workers", "--concurrency", dest="workers", type=int, default=4)
    parser.add_argument("--max-packet-chars", type=int, default=45_000)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0)
    parser.add_argument("--agent", action="append", help="Repeat to select agent strata")
    parser.add_argument("--endpoint", help="Override the Hugging Face endpoint")
    parser.add_argument("--include-transcripts", action="store_true")
    parser.add_argument(
        "--refresh-data", action="store_true",
        help="Run the incremental Hugging Face snapshot download even when parquet files exist",
    )
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Require an existing local dataset and never contact Hugging Face",
    )
    parser.add_argument("--no-commits", action="store_true")
    parser.add_argument(
        "--fresh", action="store_true",
        help="Disable resume and replace annotations for the selected output directory",
    )
    return parser


def main(default_study: int = 2) -> None:
    args = build_parser(default_study).parse_args()
    args.output_dir = args.output_dir or f"outputs/study{args.study}"
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.min_prompts < 1:
        raise SystemExit("--min-prompts must be at least 1")
    if args.max_prompts < 0:
        raise SystemExit("--max-prompts must be 0 or greater")
    if args.sample_size < 0 or (args.max_prompts and args.max_prompts < args.min_prompts):
        raise SystemExit("Require sample-size >= 0 and max-prompts = 0 or >= min-prompts")
    if args.max_packet_chars < 1000:
        raise SystemExit("--max-packet-chars must be at least 1000")
    if args.skip_download and args.refresh_data:
        raise SystemExit("--skip-download and --refresh-data cannot be used together")

    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    transcripts_missing = args.include_transcripts and not (data_dir / "transcripts").is_dir()
    needs_download = not _data_ready(data_dir, not args.no_commits) or transcripts_missing
    if args.skip_download and needs_download:
        raise SystemExit(
            f"Required dataset files are absent from {data_dir}; remove --skip-download to fetch them"
        )
    if not args.skip_download and (needs_download or args.refresh_data):
        download = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "download_data.py"),
            "--local-dir", str(data_dir),
            "--env-file", args.env_file,
        ]
        if args.endpoint:
            download.extend(["--endpoint", args.endpoint])
        if args.include_transcripts:
            download.append("--include-transcripts")
        _run(download)
    else:
        print(f"Using existing SWE-Chat parquet files in {data_dir}", flush=True)

    child_env = os.environ.copy()
    src_path = str(PROJECT_ROOT / "src")
    child_env["PYTHONPATH"] = (
        src_path + os.pathsep + child_env["PYTHONPATH"]
        if child_env.get("PYTHONPATH") else src_path
    )
    command = [
        sys.executable, "-u", "-m", "swe_chat_analysis.cli", f"run-study{args.study}",
        "--data-dir", str(data_dir),
        "--output-dir", args.output_dir,
        "--env-file", args.env_file,
        "--sample-size", str(args.sample_size),
        "--seed", str(args.seed),
        "--min-prompts", str(args.min_prompts),
        "--max-prompts", str(args.max_prompts),
        "--workers", str(args.workers),
        "--max-packet-chars", str(args.max_packet_chars),
        "--timeout", str(args.timeout),
        "--max-retries", str(args.max_retries),
        "--delay", str(args.delay),
        "--no-resume" if args.fresh else "--resume",
    ]
    for agent in args.agent or []:
        command.extend(["--agent", agent])
    if args.no_commits:
        command.append("--no-commits")
    _run(command, env=child_env)

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    completeness = summary.get("run_completeness", {})
    completed = completeness.get("annotated_session_count")
    expected = completeness.get("packet_session_count")
    pending = completeness.get("pending_or_failed_session_count")
    if isinstance(pending, int) and pending > 0:
        raise SystemExit(
            f"Study {args.study} completed {completed}/{expected} sessions; "
            "rerun the same command to resume the remaining sessions"
        )
    print(f"Study {args.study} complete: {completed}/{expected}; summary={summary_path}", flush=True)


if __name__ == "__main__":
    main()
