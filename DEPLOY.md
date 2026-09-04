# Study 2 deployment

The repository keeps dataset files, API credentials, and generated annotations out of Git. A fresh
machine only needs Python 3.10+, disk space for the SWE-Chat parquet files, a Hugging Face token with
accepted SWE-Chat access, and an OpenAI-compatible chat-completions endpoint.

## Install and configure

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

Fill `.env` locally. Do not commit it:

```dotenv
HF_TOKEN=hf_...
HF_ENDPOINT=https://huggingface.co
OPENAI_BASE_URL=https://your-service.example/v1
OPENAI_API_KEY=...
OPENAI_MODEL=your-model
OPENAI_TRUST_ENV_PROXY=false
```

SWE-Chat is gated. The account behind `HF_TOKEN` must first accept the terms on
<https://huggingface.co/datasets/SALT-NLP/SWE-chat>.

## Download, process, and run Study 2

```bash
python scripts/run_study2_pipeline.py \
  --output-dir outputs/study2_200_seed42 \
  --sample-size 200 \
  --seed 42 \
  --min-prompts 2 \
  --workers 4
```

The entrypoint performs these stages:

1. Download the required parquet tables to `data/swe-chat` if they are absent.
2. Select sessions deterministically and build auditable, bounded evidence packets.
3. Run the Study 2 v8 judge with validation repair, configurable concurrency, and resume enabled.
4. Write the aggregate metrics to `summary.json`.

Rerun the identical command after a network or API interruption. Completed annotations for the
current sample and rubric are retained; only missing or failed sessions are requested again.

Useful variants:

```bash
# Use existing parquet files without contacting Hugging Face.
python scripts/run_study2_pipeline.py --skip-download --sample-size 200 --workers 4

# Incrementally refresh the dataset snapshot before running.
python scripts/run_study2_pipeline.py --refresh-data --sample-size 200 --workers 4

# Replace annotations instead of resuming them.
python scripts/run_study2_pipeline.py --fresh --sample-size 200 --workers 4
```

The main artifacts are:

- `packets.jsonl`: processed evidence packets sent to the judge.
- `intent_annotations.jsonl`: validated per-session Study 2 annotations.
- `intent_errors.jsonl`: failures excluded from metric denominators and retried by resume.
- `summary.json`: aggregate Study 2 metrics.

