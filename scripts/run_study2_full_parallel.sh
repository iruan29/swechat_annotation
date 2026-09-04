#!/usr/bin/env bash
set -euo pipefail

study2_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
study2_project_root="$(cd "${study2_script_dir}/.." && pwd)"
study2_workers="${STUDY2_WORKERS:-200}"
study2_output_dir="${STUDY2_OUTPUT_DIR:-outputs/study2_full}"

if ! [[ "${study2_workers}" =~ ^[1-9][0-9]*$ ]]; then
  echo "STUDY2_WORKERS must be a positive integer" >&2
  exit 2
fi

cd "${study2_project_root}"

exec python scripts/run_study2_pipeline.py \
  --output-dir "${study2_output_dir}" \
  --sample-size 0 \
  --seed 42 \
  --min-prompts 2 \
  --max-prompts 0 \
  --workers "${study2_workers}" \
  "$@"
