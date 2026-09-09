---
license: odc-by
task_categories:
  - text-generation
language:
  - en
tags:
  - code
  - agent
  - traces
  - human-ai-collaboration
  - agent-traces
  - coding-agent
  - coding-sessions
pretty_name: SWE-chat
size_categories:
  - 1M<n<10M
configs:
  - config_name: conversations
    data_files:
      - split: train
        path: conversations.parquet
  - config_name: sessions
    data_files:
      - split: train
        path: sessions.parquet
  - config_name: session_logs
    data_files:
      - split: train
        path: session_logs.parquet
  - config_name: checkpoints
    data_files:
      - split: train
        path: checkpoints.parquet
  - config_name: commits
    data_files:
      - split: train
        path: commits.parquet
  - config_name: repositories
    data_files:
      - split: train
        path: repositories.parquet
---

# SWE-chat: Coding Agent Interactions From Real Users in the Wild

- 📄 **Paper:** [arxiv.org/abs/2604.20779](https://arxiv.org/abs/2604.20779)
- 🌐 **Website:** [swe-chat.com](https://www.swe-chat.com/)

## Dataset Summary

SWE-chat captures **real-world AI coding sessions** from developers using AI coding assistants (Claude Code, Codex, Gemini CLI, and others via the [Entire.io](https://entire.io) CLI). Each session includes the full conversation transcript, tool calls, thinking traces, code changes, and attribution of human vs. agent-authored code.

### Dataset Size

| Table | Rows |
|---|---|
| `repositories` | 205 |
| `checkpoints` | 13,406 |
| `sessions` | 5,851 |
| `session_logs` | 5,851 |
| `commits` | 14,459 |
| `conversations` | 2,692,480 |
| `transcripts/*.jsonl` (files) | 5,851 |

### Tables

| Table | Description | Key |
|---|---|---|
| **conversations** | All transcript entries: user prompts, assistant responses, thinking, tool calls, tool results, metadata events | `turn_id` |
| **sessions** | One row per coding session with metadata, token usage, and attribution | `session_id` |
| **session_logs** | Per-session transcript pointer (`transcript_path`) plus auxiliary text fields | `session_id` |
| **checkpoints** | Checkpoint snapshots linking sessions to commits | `checkpoint_pk` |
| **commits** | Git commits with diffs, file states, and agent/human attribution | `commit_sha` |
| **repositories** | Repository metadata, settings, and GitHub API enrichment | `repo_id` |

## Loading the Data

```python
from datasets import load_dataset

# Load individual tables (each table is exposed as a named config)
conversations = load_dataset("SALT-NLP/SWE-chat", "conversations", split="train")
sessions = load_dataset("SALT-NLP/SWE-chat", "sessions", split="train")
commits = load_dataset("SALT-NLP/SWE-chat", "commits", split="train")

# Or load with pandas directly
import pandas as pd
df_conv = pd.read_parquet("conversations.parquet")
df_sessions = pd.read_parquet("sessions.parquet")

# Raw transcripts live under transcripts/{session_id}.jsonl
# session_logs.parquet holds the relative path + auxiliary text fields
df_session_logs = pd.read_parquet("session_logs.parquet")
with open(df_session_logs["transcript_path"].iloc[0]) as f:
    raw_transcript = f.read()
```

### Quick Examples

```python
import pandas as pd

conversations = pd.read_parquet("conversations.parquet")
sessions = pd.read_parquet("sessions.parquet")

# Clean user-assistant conversation (no tool calls/thinking)
conv = conversations[conversations.is_conversational]
print(conv[["conversation_turn_number", "role", "content"]].head(10))

# All tool calls with extracted file paths
tools = conversations[conversations.turn_type == "tool_use"]
print(tools[["tool_name", "file_path", "command"]].head())

# Agent thinking traces
thinking = conversations[conversations.turn_type == "assistant_thinking"]

# Sessions with high agent-authored code percentage
high_agent = sessions[sessions.agent_percentage > 90]

# Join conversations to sessions for richer context
merged = conversations.merge(
    sessions[["session_id", "repo_id", "agent_percentage"]],
    on="session_id"
)
```

## Dataset Schema

### Relationship Map

```
repositories (1) ───-> (N) checkpoints    [repo_id]
checkpoints (N) ←──-> (M) sessions        [JSON arrays on both sides]
checkpoints (1) ───-> (N) commits          [checkpoint_pk]
sessions (1) ───-> (1) session_logs        [session_id]
sessions (1) ───-> (N) conversations       [session_id]
```

### ID Strategy

| Entity | Primary Key | Format | Globally Unique? |
|---|---|---|---|
| Repository | `repo_id` | `owner/repo` | Yes |
| Checkpoint | `checkpoint_pk` | `{repo_id}#{checkpoint_id}` | Yes |
| Session | `session_id` | UUID from agent | Yes |
| Commit | `commit_sha` | 40-hex SHA | Yes |
| Conversation turn | `turn_id` | `{session_id}#{turn_number}` | Yes |

---

### 1. `conversations.parquet`

One row per conversation turn (user prompt, assistant response, assistant thinking step, tool call, or metadata event). Filter with `is_conversational=True` for a clean user-assistant dialogue view.

**Two turn columns:**
- `turn_number`: sequential across ALL rows in the session (including tool calls)
- `conversation_turn_number`: sequential ONLY for `is_conversational=True` rows. NULL for tool/thinking rows

| Column | Type | Description |
|---|---|---|
| `turn_id` | string | **PK**. `{session_id}#{turn_number}` |
| `session_id` | string | FK -> sessions |
| `checkpoint_pk` | string | FK -> checkpoints (canonical) |
| `repo_id` | string | FK -> repositories |
| `user_id` | string | Commit author (`sessions.user_id`) |
| `turn_number` | int | 0-based sequential index across ALL rows |
| `conversation_turn_number` | int | Sequential index for conversational rows only. NULL for tool/thinking rows |
| `role` | string | `user`, `assistant`, `tool_use`, `tool_result`, or `metadata` |
| `turn_type` | string | `user_prompt`, `system_injected`, `assistant_response`, `assistant_thinking`, `tool_use`, `tool_result`, `summary`, `system_event`, `file_snapshot`, `progress`, `queue_operation` |
| `is_conversational` | bool | True for `user_prompt` and `assistant_response` |
| `content` | string | Prompt text, response text, thinking text, tool input JSON, or result text (truncated to 10KB for tool_result) |
| `model` | string | Model name (e.g. `claude-opus-4-6`). NULL for user/tool_result/metadata rows |
| `timestamp` | timestamp | Entry timestamp |
| `input_tokens` | int | From usage (assistant_response only) |
| `output_tokens` | int | From usage (assistant_response only) |
| `cache_creation_input_tokens` | int | Cache creation tokens from API usage (assistant_response only) |
| `cache_read_input_tokens` | int | Cache read tokens from API usage (assistant_response only) |
| `is_continuation` | bool | User turn starts with "This session is being continued" |
| `is_first_turn` | bool | First conversational turn in session |
| `word_count` | int | Word count of content |
| `char_count` | int | Character count of content |
| `tool_name` | string | Tool name for tool_use/tool_result rows. Claude: Read, Write, Edit, NotebookEdit, Bash, Grep, Glob, WebFetch, WebSearch, Task, etc. Gemini: read_file, write_file, edit_file, run_command, etc. |
| `tool_call_id` | string | The `toolu_` ID linking tool_use to tool_result |
| `file_path` | string | Extracted from file-modifying/reading tool input. Handles `file_path`, `notebook_path` (NotebookEdit), `path`/`filename` (Gemini) |
| `command` | string | Extracted from Bash / run_command / shell tool input |
| `pattern` | string | Extracted from Grep/Glob tool input |
| `tool_input_json` | string (JSON) | Full tool input parameters for tool_use rows |
| `category` | string | `Research` / `Action` / `Orchestration` / `Other` for tool rows |
| `bash_category` | string | git / package manager / test-build / file ops / other for Bash/shell tools |
| `queue_op_subtype` | string | For `queue_operation` rows only. One of: `user_prompt_enqueued` (user typed while agent busy), `user_prompt_delivered` (queued message was sent to agent), `user_prompt_discarded` (queued message was removed without delivery), `task_notification` (completed subagent result), `other`. NULL for all other turn types. |
| `agent` | string | Agent name (denormalized from session) |
| `strategy` | string | Strategy (denormalized from session) |
| `language` | string | Detected natural language of the user prompt (populated for `user_prompt` rows only). Outside the allowlist of supported languages the value is recoded to `english`. |
| `prompt_intent` | string | LLM-annotated intent of a user prompt (turn_type=`user_prompt`). One of: `create new code`, `refactor`, `debug`, `understand`, `connect`, `git`, `test`, `other`. NULL for non-prompt rows or unannotated prompts. See paper for more details. |
| `prompt_pushback` | string | LLM-annotated pushback class for a user prompt (turn_type=`user_prompt`). One of: `correction`, `rejection`, `failure_report`, `pacing_complaint`, `takeover`, `requirement_change`, `non_pushback`. NULL for non-prompt rows or unannotated prompts. See paper for more details. |

#### Row types produced from transcript entries

| Source | turn_type | role | is_conversational |
|---|---|---|---|
| User text message | `user_prompt` | `user` | True |
| System-injected user message (skill invocations, local command output, meta) | `system_injected` | `user` | False |
| Assistant text blocks | `assistant_response` | `assistant` | True |
| Assistant thinking blocks | `assistant_thinking` | `assistant` | False |
| Assistant tool_use blocks | `tool_use` | `tool_use` | False |
| User tool_result blocks | `tool_result` | `tool_result` | False |
| Session summary entries | `summary` | `metadata` | False |
| System/hook event entries | `system_event` | `metadata` | False |
| File history snapshot entries | `file_snapshot` | `metadata` | False |
| Progress entries (hooks, etc.) | `progress` | `metadata` | False |
| Queue operation entries | `queue_operation` | `metadata` | False |

**Note on `queue_operation` rows:** Claude Code queues messages when the agent is busy. The `queue_op_subtype` column distinguishes: (a) user prompts typed while agent was running (`user_prompt_enqueued`), which may have been delivered (`user_prompt_delivered`) or silently discarded before reaching the agent (`user_prompt_discarded`); and (b) completed subagent results (`task_notification`). The `content` column contains the plain-text prompt or the `<task-notification>` XML payload; it is empty for `dequeue` and `remove` operations.


### 2. `sessions.parquet`

| Column | Type | Description |
|---|---|---|
| `session_id` | string | **PK**. UUID from agent |
| `repo_id` | string | FK -> repositories |
| `owner_id` | string | Repository owner (from `repo_id` split) |
| `user_id` | string | Commit author resolved via GitHub API. |
| `checkpoint_ids` | string (JSON) | All checkpoint_pks referencing this session |
| `canonical_checkpoint_pk` | string | FK -> checkpoints (source for dedup) |
| `agent` | string | e.g. "Claude Code", "Gemini CLI" |
| `strategy` | string | Entire CLI strategy (e.g. "auto", "manual") |
| `branch` | string | Git branch the session was recorded on |
| `created_at` | timestamp | Session creation time |
| `cli_version` | string | Version of the Entire CLI that recorded the session |
| `files_touched` | string (JSON) | List of file paths touched during the session |
| `files_touched_count` | int | Number of files touched |
| `checkpoints_count` | int | Number of checkpoints created during the session |
| `input_tokens` | int | Total input tokens consumed |
| `output_tokens` | int | Total output tokens generated |
| `cache_creation_tokens` | int | Tokens used for prompt cache creation |
| `cache_read_tokens` | int | Tokens read from prompt cache |
| `api_call_count` | int | Number of API calls made |
| `agent_lines` | float | Lines of code authored by the agent. |
| `human_added` | float | Lines added by the human. |
| `human_modified` | float | Lines modified by the human. |
| `human_removed` | float | Lines removed by the human. |
| `total_committed` | float | Total lines committed. |
| `agent_percentage` | float | Percentage of committed code authored by the agent (0-100). |
| `attribution_calculated_at` | timestamp | When the attribution was computed |
| `transcript_identifier_at_start` | string | Transcript identifier at the start of the session |
| `transcript_path` | string | Path to the transcript file |
| `tool_call_count` | int | Total tool calls in this session |
| `unique_tools_count` | int | Number of distinct tools used |
| `research_count` | int | Count of research tool calls (Read/Grep/Glob/WebFetch/WebSearch/read_file/grep/glob/list_directory) |
| `action_count` | int | Count of action tool calls (Write/Edit/NotebookEdit/Bash/write_file/edit_file/run_command/etc.) |
| `first_write_position` | int | Position of the first file-modifying tool call. |
| `duration_seconds` | float | Estimated session duration in seconds (from transcript timestamps) |
| `turn_count` | int | Number of conversational turns |
| `prompt_count` | int | Non-continuation user turns |
| `content_hash` | string | SHA256 from content_hash.txt |
| `user_persona` | string | LLM-annotated persona of the session's primary user. One of: `Expert Nitpicker`, `Vague Requester`, `Mind Changer`, `Other`. NULL for unannotated sessions. See paper for more details. |
| `session_success` | string | LLM-annotated session success score (0-100, as a string). NULL for unannotated sessions. See paper for more details. |

### 2b. `session_logs.parquet`

One row per session. The raw JSONL/JSON transcript is stored as a file under `transcripts/{session_id}.jsonl` (or `.json` for Gemini CLI) and referenced by the `transcript_path` column. Join to `sessions` on `session_id`.

| Column | Type | Description |
|---|---|---|
| `session_id` | string | **PK / FK -> sessions** |
| `transcript_path` | string | Path to the session's transcript file under `transcripts/` |
| `context_md` | string | Full content of `context.md` |
| `session_metadata_raw` | string (JSON) | Raw `metadata.json` content |

### 3. `checkpoints.parquet`

| Column | Type | Description |
|---|---|---|
| `checkpoint_pk` | string | **PK**. `{repo_id}#{checkpoint_id}` |
| `checkpoint_id` | string | 12-hex ID |
| `repo_id` | string | FK -> repositories |
| `session_pks` | string (JSON) | FK list -> sessions |
| `session_count` | int | Number of sessions in this checkpoint |
| `commit_shas` | string (JSON) | FK list -> commits |
| `commit_count` | int | Number of commits in this checkpoint |
| `author_user_ids` | string (JSON) | Unique user_ids of commit authors |
| `unique_author_count` | float | Number of distinct commit authors |
| `user_id` | string | Set when checkpoint has a single author. |
| `cli_version` | string | Version of the Entire CLI |
| `strategy` | string | Entire CLI strategy |
| `branch` | string | Git branch |
| `checkpoints_count` | int | From metadata: total checkpoints in the session |
| `files_touched` | string (JSON) | List of file paths touched |
| `files_touched_count` | int | Number of files touched |
| `cp_input_tokens` | int | Checkpoint-level aggregated input tokens |
| `cp_output_tokens` | int | Checkpoint-level aggregated output tokens |
| `cp_cache_creation_tokens` | int | Checkpoint-level aggregated cache-creation tokens |
| `cp_cache_read_tokens` | int | Checkpoint-level aggregated cache-read tokens |
| `cp_api_call_count` | int | Checkpoint-level aggregated API call count |
| `total_additions` | int | Sum of added lines across commits in this checkpoint |
| `total_deletions` | int | Sum of deleted lines across commits in this checkpoint |
| `checkpoint_metadata_raw` | string (JSON) | Raw metadata.json |

### 4. `commits.parquet`

| Column | Type | Description |
|---|---|---|
| `commit_sha` | string | **PK** |
| `checkpoint_pk` | string | FK -> checkpoints |
| `repo_id` | string | FK -> repositories |
| `commit_index` | int | 0-based within checkpoint |
| `num_commits` | int | Total commits for this checkpoint |
| `user_id` | string | Canonical user identity: GitHub username if resolved, else email, else author name. |
| `github_username` | string | GitHub username resolved via commit API. |
| `author_name` | string | Git author name |
| `author_email` | string | Git author email |
| `author_date` | timestamp | Git author timestamp |
| `commit_date` | timestamp | Git commit timestamp |
| `commit_message` | string | Commit message |
| `branch` | string | Git branch the commit was observed on |
| `is_agent_author` | bool | Author matches agent patterns |
| `files_changed_count` | int | Number of files touched in this commit |
| `total_additions` | int | Lines added in this commit |
| `total_deletions` | int | Lines removed in this commit |
| `files_changed` | string | Raw git name-status |
| `numstat` | string | Raw git numstat |
| `patch` | string | Full unified diff |
| `agent_changes` | string (JSON) | Agent file-modification tool calls |
| `file_attribution` | string (JSON) | Per-file: agent_only / human_only / mixed |
| `status` | string | "ok" or error |


### 5. `repositories.parquet`

| Column | Type | Description |
|---|---|---|
| `repo_id` | string | **PK**. `owner/repo` |
| `owner_id` | string | Owner part of `repo_id` |
| `name` | string | Short repo name |
| `url` | string | GitHub URL |
| `is_fork` | bool | Whether the repo is a fork on GitHub |
| `settings` | string (JSON) | Raw `settings.json` from the Entire CLI |
| `num_checkpoints` | int | Checkpoints for this repo in the dataset |
| `num_sessions` | int | Sessions for this repo in the dataset |
| `num_commits` | int | Commits for this repo in the dataset |
| `num_contributors_in_dataset` | int | Distinct commit authors for this repo in the dataset |
| `total_additions_in_dataset` | int | Lines added across dataset commits for this repo |
| `total_deletions_in_dataset` | int | Lines removed across dataset commits for this repo |
| `total_repo_commits_ever` | int | All commits in repo history (GitHub) |
| `total_repo_additions_ever` | int | All additions in repo history (GitHub) |
| `total_repo_deletions_ever` | int | All deletions in repo history (GitHub) |
| `total_agent_commits_ever` | int | Commits by agent-like authors across full repo history |
| `total_agent_additions_ever` | int | Additions by agent-like authors across full repo history |
| `total_agent_deletions_ever` | int | Deletions by agent-like authors across full repo history |
| `last_scraped_at` | timestamp | When repo metadata was last scraped |
| `license_type` | string | Usable-license classification from the curated license registry |
| `repo_github_metadata` | string (JSON) | Full GitHub `/repos/{owner}/{repo}` response |
| `repo_type_domain` | string | LLM-annotated repo domain. One of: `application`, `library`, `devtools`, `other`. See paper for more details. |
| `repo_type_audience` | string | LLM-annotated repo target audience. One of: `enduser`, `developer`, `researchers`, `education`. See paper for more details. |

## Data Collection

### Source

Data is collected from public GitHub repositories that use the [Entire.io](https://entire.io) CLI to checkpoint their AI coding sessions. The Entire CLI creates checkpoints on a special branch (`entire/checkpoints/v1`) containing:

- Session metadata (agent, strategy, token usage, code attribution)
- Full conversation transcripts (JSONL for Claude Code, JSON for Gemini CLI)
- User prompts and context

### Supported Agents

- Claude Code
- OpenAI Codex
- Gemini CLI
- Cursor
- OpenCode
- GitHub Copilot CLI

### PII Redaction

We redacted personally identifiable information in all user prompts and assistant text responses using Microsoft Presidio (named-entity detection) and TruffleHog (secret detection).

### Deduplication Strategy

Sessions may appear in multiple checkpoints (a session spans checkpoint boundaries). We deduplicate on `session_id`, keeping the record with the highest `output_tokens` (most complete). The `checkpoint_ids` column preserves the full list of checkpoints each session appeared in.

### Data Removal Requests

If you would like your data removed from SWE-chat, or if you encounter content that is illegal, you may request deletion.
To do so, please contact us via [joachimbaumann@stanford.edu](mailto:joachimbaumann@stanford.edu). Please include **`repo_id`**, **`session_id`**, or **`turn_id`** values corresponding to the entries you wish to remove, and a brief explanation of the reason for removal.

### Citation

Please consider citing the following papers if you find this dataset useful:

```bibtex
@article{baumann2026swechat,
  title={SWE-chat: Real-World AI Coding Sessions in the Wild},
  author={Baumann, Joachim and Padmakumar, Vishakh and Li, Xiang and Yang, John and Yang, Diyi and Koyejo, Sanmi},
  year={2026},
  journal={arXiv preprint arXiv:2604.20779},
  url={https://arxiv.org/pdf/2604.20779}
}
```
