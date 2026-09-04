#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from swe_chat_analysis.env import load_dotenv  # noqa: E402


def validate_download(path: str | Path) -> Path:
    local = Path(path)
    required = [local / "sessions.parquet", local / "conversations.parquet"]
    missing = [item.name for item in required if not item.is_file() or item.stat().st_size == 0]
    if missing:
        raise RuntimeError(
            "Hub client returned without downloading required files: " + ", ".join(missing)
        )
    return local


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the gated SWE-Chat dataset")
    parser.add_argument("--local-dir", default="data/swe-chat")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--endpoint", default=None,
        help="Hub endpoint; defaults to HF_ENDPOINT, then https://hf-mirror.com",
    )
    parser.add_argument(
        "--include-transcripts", action="store_true",
        help="Also download all 5,851 raw transcript files; parquet is sufficient for this pipeline",
    )
    args = parser.parse_args()
    load_dotenv(args.env_file)
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if not token:
        parser.error(
            "SWE-Chat is gated. Accept its terms at "
            "https://huggingface.co/datasets/SALT-NLP/SWE-chat and put HF_TOKEN in .env"
        )
    endpoint = args.endpoint or os.getenv("HF_ENDPOINT") or "https://hf-mirror.com"
    patterns = ["*.parquet", "README.md", ".gitattributes"]
    if args.include_transcripts:
        patterns.append("transcripts/**")
    try:
        path = snapshot_download(
            repo_id="SALT-NLP/SWE-chat",
            repo_type="dataset",
            local_dir=args.local_dir,
            allow_patterns=patterns,
            token=token,
            endpoint=endpoint,
        )
        validate_download(path)
    except Exception as error:
        if "hf-mirror" in endpoint:
            print(
                f"Mirror failed ({error}). Retrying the official endpoint; the mirror may redirect gated files.",
                file=sys.stderr,
            )
            path = snapshot_download(
                repo_id="SALT-NLP/SWE-chat",
                repo_type="dataset",
                local_dir=args.local_dir,
                allow_patterns=patterns,
                token=token,
                endpoint="https://huggingface.co",
            )
            validate_download(path)
        else:
            raise
    local = validate_download(path)
    parquet_count = len(list(local.glob("*.parquet")))
    size_gib = sum(item.stat().st_size for item in local.rglob("*") if item.is_file()) / 1024**3
    print(f"Downloaded SWE-Chat to {local} ({parquet_count} parquet files, {size_gib:.2f} GiB)")


if __name__ == "__main__":
    main()
