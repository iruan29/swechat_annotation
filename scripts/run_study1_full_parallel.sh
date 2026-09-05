#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}/.."
exec python scripts/run_study1_pipeline.py \
  --output-dir "${STUDY1_OUTPUT_DIR:-outputs/study1_full_v6}" \
  --sample-size 0 --seed 42 --min-prompts 2 --max-prompts 0 \
  --workers "${STUDY1_WORKERS:-200}" "$@"
