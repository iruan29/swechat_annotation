# SWE-Chat：instruction 不是 objective

这个项目检验以下观点在真实 coding-agent 会话中是否得到数据支持：

> Agents should optimize for project outcomes under partial observability, treating instructions and execution observations as evidence about the project rather than treating each instruction as the objective itself.

Pipeline 对每个会话保留完整的 user prompt 序列，并加入 assistant/tool 轨迹与关联 commit 摘要。LLM judge 不直接判断观点“对不对”，而是按中性 rubric 标注可观察现象，再由确定性代码聚合指标。

新机器上的完整 Study 2 部署与一键运行说明见 [`DEPLOY.md`](DEPLOY.md)。

SWE-Chat 自带的 `prompt_pushback`、`user_persona`、`session_success` 标签会保留在本地 packet 用于外部校验，但在调用新 judge 时会被隐藏，避免循环论证。

## 两个独立研究 pipeline

### Study 1：要求在交互中形成

这个 pipeline 将 session 划分为 task threads，并为每个 final material requirement 分配稳定
ID，标注从“初始是否明确”到“何时可发现、何时被识别、何时正确实现”的 lifecycle：

- `initial_instruction_requirement_coverage`：初始指令明确包含的最终要求比例，并报告 0–4
  specificity score。
- `post_initial_material_update_basis.project_grounded_rate`：初始指令之后、由用户表达且会改变
  可接受成果的更新中，project-grounded requirement 的比例；同时保留 preference/mixed/unclear。
- `terminal_requirement_discovery`：晚出现的 project-grounded requirements 的最早可发现时间、
  discovery status 和 evidence-path source 分布，以及其中本可更早发现的比例。
- `cost_of_delayed_project_understanding`：比较存在/不存在 delayed project understanding 的
  session 在 human rewrite/removal、linked-commit deletion、committed-agent-code-share proxy、turns、tool/API calls、
  tokens、duration 和跨 requirement regression 上的描述性差异；另算 evidence-to-correct-
  implementation 的 turn/time latency。
- `agent_response_to_evolving_project_evidence`：区分提前发现并完成、主动询问后完成、新证据后
  正确更新、只补表面症状、忽略证据、满足新要求但破坏旧要求，以及证据不足/未解决。
- 保留旧版 `material_requirement_emergence_rate`、literal sufficiency 和
  `behavior_level_distribution`，便于与既有结果对照。

前两个指标使用完整会话。行为指标单独调用 judge；每次只发送截至该 episode 结束时可见的历史，不发送后续消息、commit 或全局 outcome metadata，避免 hindsight leakage。提示词及确定性分类规则在 `src/swe_chat_analysis/study1.py`。

Requirement rubric 将“要求由谁表达”与“什么触发用户提出该要求”分开。Trigger
包括 execution error、test/CI、observed output、repository/dependency constraint、agent
explanation、review、spontaneous revision 和 unclear；只有具有 explicit/strong 因果联系的
前六类才计入 `observation_or_feedback_triggered_event_rate`。非用户表达的 event 会被确定性归一为
`not_user_articulated`；非 material event 不要求存在 `first_explicit_turn`。

成本比较是描述性 association，不是因果估计。数据没有完整的逐行历史快照，因此
`human_rework_lines = human_modified + human_removed`；linked commits 可能对应多个 session；
`committed_agent_code_share` 只是 authorship-based code-survival proxy，不能解释为严格的
longitudinal line survival。

运行 20 个 session：

```bash
PYTHONPATH=src python -m swe_chat_analysis.cli run-study1 \
  --data-dir data/swe-chat \
  --output-dir outputs/study1_20_seed42 \
  --sample-size 20 \
  --seed 42 \
  --workers 4
```

Study 1 会生成 `requirement_annotations.jsonl`、`behavior_annotations.jsonl` 和聚合后的
`summary.json`。由于行为标注以 episode 为单位，LLM 请求数会高于 session 数。

### Study 2：用户 belief、表面 instruction 与实际情况

这个 pipeline 从用户的表面 instruction 中标注其背后可由会话证据支持的 `user_belief`，
再将该 instruction 与 repository、测试、错误、运行输出、review 或用户确认所支持的
`actual_project_situation` 比较。Mental-state 字段是有证据强度的推断，不被表述为直接读取用户内心：

- `material_instruction_reality_mismatch_rate`：表面 instruction 与可识别的实际项目情况存在
  material mismatch 的 task-thread 比例。Mismatch 包括字面执行会直接冲突、解决错误问题、采用
  无法实现底层目标的手段，或遗漏后来由用户纠正/拒绝所确认的 scope、source-of-truth、验收、
  兼容性、安全或功能条件，从而造成拒绝或非平凡返工；不包括无害实现选择、Agent 自身执行错误，
  或能由合理默认值解决的一般性 underspecification。对同一底层目标的后续纠正保留在原 task
  thread 中，不会通过拆分 thread 隐藏初始 mismatch。
- `gap_driver`：belief 形成来源，包括个人偏好/价值、既往经历或类比、领域/技术知识背景、
  当前项目知识、本次会话中的 observation/feedback、外部信息或建议、无明确来源的假设、mixed
  和 unclear；同时报告 explicit/strong/weak/insufficient evidence strength、belief 是否可识别，
  以及 belief 的信息基础是 `partial_observation`、`broadly_grounded`、`non_observational` 还是
  `unclear`。`partial_observation_belief_rate` 直接衡量 mismatch 是否源于对局部症状、单次输出、
  局部代码或过时状态的片面观察。
- `mismatch_discoverability_and_route`：mismatch 是否从初始项目状态即可发现、是否早于用户解释
  已有证据、evidence path 来源分布，以及 agent 使用 targeted question、repository inspection、
  test/CI、execution、observed output、prior context、alternative comparison 或 causal reasoning
  等方法发现问题的分布。
- `literal_compliance_but_reality_failure_rate`：字面 instruction 可以完成，但未解决实际情况，
  且失败由 instruction–reality mismatch 而非 agent 能力不足造成的比例。
- `agent_gap_detection_and_response`：在全部 material mismatch threads 中，衡量 agent 是否主动
  consider 用户的 latent goal/preference/assumption/knowledge，并将 response 确定性分为：直接遵守
  `follows_surface_instruction`、针对 material uncertainty 做 targeted clarification、识别 instruction
  与实际情况的冲突并有依据地挑战/偏离 instruction，以及 mixed/unclear；另报告 earliest evidence
  到 mental-state consideration、gap detection 和 actual-situation resolution 的 turn/time latency。
  Mental-state consideration 必须显式连接表面要求与用户潜在目标/假设；普通代码检查、测试或实现
  选择问题不计。互斥 response pattern 由事件先后派生：`surface_action_commitment_turn` 记录首次
  真正提交执行表面方案的时点；为验证前提而进行的代码阅读、repository inspection、文档研究、
  diagnostic test 和方案比较不算执行。如果 agent 在 commitment 前发现 gap 并停下或改道，归为
  `detects_reality_gap_and_resists`；在 commitment 前询问 material uncertainty，归为 clarification；
  先 commitment、后发现或修复才归为 `follows_surface_instruction`。
- `observed_resolution_by_agent_response`：分别计算三类 agent response 最终 resolved/partial/
  unresolved/unknown 的分布和 resolved rate。
- `cost_of_faithful_execution_under_mismatch`：在 session 层面对比“先忠实执行了存在 mismatch 的
  instruction”与“未先执行、而是早期澄清或有证据地挑战”的 human rework、commit deletion、
  committed-agent-code-share proxy、turns、tool/API calls、tokens 和 duration。该比较是描述性关联，
  不解释为因果效应。

提示词和证据门槛在 `src/swe_chat_analysis/study2.py`。运行同一随机种子的 20 个 session：

```bash
PYTHONPATH=src python -m swe_chat_analysis.cli run-study2 \
  --data-dir data/swe-chat \
  --output-dir outputs/study2_20_seed42 \
  --sample-size 20 \
  --seed 42 \
  --workers 4
```

Study 2 会生成 `intent_annotations.jsonl` 和 `summary.json`。两个命令使用相同采样参数，
因此可分析同一组 session。

Study 1 和 Study 2 的 judge 命令均支持 `--workers N`（别名 `--concurrency N`）并发调用。
默认值为 1；同一 worker 内的 validation repair 顺序执行，因此任一时刻的 HTTP 请求数不会
超过该上限。输出仍由主线程逐行写入，`--resume` 和错误隔离语义不变。并发数应根据服务端
rate limit 调整；遇到 HTTP 429 时降低 workers 或增加 `--delay`。

## 指标

| 指标 | 操作化定义 | 对应问题 |
|---|---|---|
| Initial requirement coverage | 初始指令明确表达的 final material requirements / 全部 final material requirements | 初始指令是否足以界定验收 |
| Project-grounded update share | 用户后续 material updates 中由项目证据/功能约束决定的比例 | 更新是项目需求还是个人偏好 |
| Earlier-discoverable rate | 晚出现的 project-grounded requirements 中，证据在明确表达前已经可用的比例 | agent 本可提前发现什么 |
| Delayed-understanding cost contrast | 有/无延迟理解 session 的 rework/survival proxy、交互成本、latency 与 regression 描述性差异 | 理解延迟对应什么成本 |
| User-belief gap driver | preference、experience、knowledge、observation、external advice 或 unsupported assumption 等来源及证据强度 | 用户为何会形成支撑表面 instruction 的 belief |
| Mismatch discoverability/route | 初始可发现率、早于用户解释的可发现率、证据路径与 agent detection method | gap 在何时、通过什么证据可以被发现 |
| Literal compliance/reality failure | 字面指令可以完成但实际项目情况仍未解决 | 只遵守表面 instruction 是否足够 |
| Agent gap response | 在 mismatch 中直接遵守、澄清歧义、或识别现实冲突后挑战/偏离 instruction | agent 是否考虑用户 mental state 并发现 instruction–reality gap |
| Detection/resolution latency | earliest mismatch evidence 到 mental-state consideration、gap detection、实际问题被处理的 turns/time | agent 发现和修正分歧有多慢 |
| Resolution by response | 各 response pattern 的 resolved/partial/unresolved/unknown 与 resolved rate | 澄清或挑战是否对应更好的目标完成情况 |
| Faithful-execution cost contrast | 先执行 mismatch instruction 与早期澄清/挑战 session 的 rework、interaction 和 code-survival proxy 对比 | 忠实执行片面 instruction 对应什么成本 |

H3 以 instruction episode 为单位，三个 mode 互斥，并同时报告全部 episodes 与 project-reasoning opportunity 条件下的比例。Episode CI 使用按 session 聚类的 bootstrap；普通读文件、例行测试、请求许可和用户报错后修复都不算 project-outcome reasoning。

## 1. 下载数据

SWE-Chat 是 gated dataset。先登录并在[官方数据页](https://huggingface.co/datasets/SALT-NLP/SWE-chat)接受条款，然后：

```bash
# 编辑当前目录已经创建的 .env，填入 HF_TOKEN
python scripts/download_data.py
```

默认下载分析所需的所有 parquet（约 2.4GB）到 `data/swe-chat/`。如需完整 5,851 份原始 transcript：

```bash
python scripts/download_data.py --include-transcripts
```

脚本默认尝试 `https://hf-mirror.com`；由于 gated 文件有时会被镜像重定向，失败时自动回退官方 endpoint。也可显式指定：

```bash
python scripts/download_data.py --endpoint https://huggingface.co
```

也可以直接用统一入口完成下载、处理、Study 2 标注和汇总：

```bash
python scripts/run_study2_pipeline.py \
  --output-dir outputs/study2_200_seed42 \
  --sample-size 200 --seed 42 --min-prompts 2 --workers 4
```

同一命令默认启用 resume；数据已经存在时不会重复下载，已完成的当前 rubric 标注也不会重复请求。

## 2. 配置 LLM

在 `.env` 填入任意 OpenAI chat-completions 兼容服务：

```dotenv
OPENAI_BASE_URL=https://your-service.example/v1
OPENAI_API_KEY=...
OPENAI_MODEL=your-model
OPENAI_TRUST_ENV_PROXY=false
```

API 请求使用 `POST {OPENAI_BASE_URL}/chat/completions`、`response_format=json_object`，温度为 0。结果逐条落盘，可恢复运行。
默认不继承 shell 的 `HTTP(S)_PROXY`；若服务必须通过代理访问，可设置 `OPENAI_TRUST_ENV_PROXY=true` 或传入 `--trust-env-proxy`。

## 3. 运行

无需安装包：

```bash
PYTHONPATH=src python -m swe_chat_analysis.cli run \
  --data-dir data/swe-chat \
  --output-dir outputs/main \
  --sample-size 200 \
  --seed 42
```

也可拆开运行，便于先审查发送给 LLM 的数据：

```bash
PYTHONPATH=src python -m swe_chat_analysis.cli prepare --sample-size 200
PYTHONPATH=src python -m swe_chat_analysis.cli judge --resume
PYTHONPATH=src python -m swe_chat_analysis.cli summarize
```

`--sample-size 0` 表示使用全部符合条件的会话；默认分析 `2 <= prompt_count <= 50` 的多轮会话，避免极端长 session 超过 judge context，并在报告元数据中记录该条件总体。主要参数：

- `--min-prompts 2`：要求至少两个真实 user prompt。
- `--max-prompts 0`：取消 50 prompts 上限，适合单独做极端长会话 sensitivity analysis。
- `--agent "Claude Code"`：可重复使用，限制 agent strata。
- `--no-commits`：不扫描 commit 表，速度更快，但 outcome 证据更弱。
- `--max-packet-chars 45000`：控制每个会话发给 judge 的最大文本量。
- `judge --no-resume`：覆盖 annotations；默认跳过已经成功的 session。

输出目录包括：

- `packets.jsonl`：发送给 LLM 的可审计 evidence packet。
- `annotations.jsonl`：结构化逐会话判断和 evidence。
- `errors.jsonl`：失败请求，不混入分母。Study 1/2 的 validation failure 会保存实际非法值、
  allowed values、首次 JSON 和 repair 后 JSON；resume 时只保留当前 sample 与 rubric version 的错误。
- `summary.json`：机器可读指标、分布与运行元数据。
- `report.md`：中文结果报告。

生成三级行为可视化：

```bash
python scripts/visualize_results.py \
  --summary outputs/main/summary.json \
  --output outputs/main/behavior_modes.png
```

默认展示有 project-reasoning opportunity 的 episodes；传入 `--scope overall` 可展示全部有效 episodes。输出路径也可以使用 `.svg` 获得矢量图。

## 快速 smoke test

fixture 仅用于验证代码，不能用于研究结论：

```bash
python scripts/make_fixture.py
PYTHONPATH=src python -m swe_chat_analysis.cli prepare \
  --data-dir data/fixture --output-dir outputs/fixture --sample-size 1
```

## 研究设计注意事项

1. 这是描述性证据，不是“adaptive agent 优于 literal agent”的因果实验。
2. SWE-Chat 来自主动公开 checkpoint 的开源项目用户，存在选择偏差。
3. session 与 checkpoint 是多对多关系；commit 是 outcome proxy，不保证某一变更只归属于该 session。
4. LLM judge 有测量误差。正式报告应人工复核随机样本，并对至少 10% 样本做第二模型/第二 prompt 复标，报告一致率。
5. 默认不向 API 发送完整 patch，只发送 commit message、文件与 diff 统计，降低成本与代码泄露风险。
