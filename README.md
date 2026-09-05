# SWE-Chat：全量标注与指标说明

## 1. 下载数据与启动全量标注

在项目根目录执行，使用 Python >= 3.10。首次安装依赖：

```bash
python -m pip install -e .
```

在 `.env` 中配置以下内容；`HF_TOKEN` 对应账号须先取得 [SWE-Chat 数据集](https://huggingface.co/datasets/SALT-NLP/SWE-chat)的访问权限：

```dotenv
HF_TOKEN=hf_...
OPENAI_BASE_URL=https://your-service.example/v1
OPENAI_API_KEY=...
OPENAI_MODEL=your-model
OPENAI_TRUST_ENV_PROXY=false
```

### 一键下载数据

```bash
python scripts/download_data.py --endpoint https://huggingface.co
```

数据保存到 `data/swe-chat/`。标注使用 parquet 表，无需额外下载原始 transcripts。

### Study 1：全量标注，200 并行

```bash
python scripts/run_study1_pipeline.py --endpoint https://huggingface.co --output-dir outputs/study1_full_v6 --sample-size 0 --seed 42 --min-prompts 2 --max-prompts 0 --workers 200
```

当前版本为 requirements **v6**、behavior **v4**。

### Study 2：全量标注，200 并行

```bash
python scripts/run_study2_pipeline.py --endpoint https://huggingface.co --output-dir outputs/study2_full_clean_v2 --sample-size 0 --seed 42 --min-prompts 2 --max-prompts 0 --workers 200
```

当前版本为 **v8**。

两个命令各自自动完成：**缺失数据下载 → 筛选与处理 → 标注 → 指标汇总 → 完整性检查**，互不依赖。
默认支持续跑，中断或部分失败后重新执行同一命令即可；不要同时运行两个进程写同一输出目录。
200 是每个命令的并发上限，两个同时运行会合计最多 400；服务限流时降低 `--workers`。

`--sample-size 0` 表示全部合格 session；`--max-prompts 0` 取消提示数上限。
合格 session 必须满足元数据至少 2 个 prompts，且事件表至少 2 条非续接摘要的 user prompts。
本地快照共 **4,384 个合格 session**：Study 1 为 **62,066 个名义标注任务**（4,384 要求任务 + 57,682 行为 episode），Study 2 为 **4,384 个任务**，重试与 repair 另计。

最终指标分别位于：

- `outputs/study1_full_v6/summary.json`
- `outputs/study2_full_clean_v2/summary.json`

同目录的 `packets.jsonl` 是处理后的证据；`*_annotations.jsonl` 保存逐条标注，`*_errors.jsonl` 保存失败历史。

## 2. 指标的共同约定

- **Session**：一次会话，也是 sample 单位；**task thread**：会话内同一项目目标；**instruction episode**：一条用户指令及下一条用户指令前的响应。
- **Material requirement**：会改变可接受成果的重要要求。普通措辞调整、授权、流程提醒不自动算 material 更新。
- `estimate = numerator / denominator`；分母为零时返回 `null`，不是 0%。
- `distribution` 是计数；多标签类型或证据路径来源的合计可能超过 thread 数。
- `mean` / `median` / `n` 为有效数值的均值、中位数和样本数；缺失不补零。
- 当前结果是描述性统计，没有显著性检验或因果效应。所有结论还受 LLM 标注误差、证据截断及样本选择影响。

## 3. Study 1：要求演化与 agent 响应

### 证据充分性

三个字段独立判断，不能把“缺少成功测试结果”直接等同于“无法识别要求”：

| 字段 | 含义 |
|---|---|
| `evidence_sufficient` | 是否足以识别最终要求及初始指令的表达内容；决定要求覆盖率的纳入范围 |
| `evolution_evidence_sufficient` | 是否足以识别要求更新历史；决定演化指标的纳入范围 |
| `implementation_evidence_sufficient` | 是否有足够证据验证实现情况，不作为要求覆盖率的成功筛选门槛 |
| `annotation_coverage` | 各类有效 session、thread、episode 及 scope 外 episode 的数量，用于核对排除情况 |

### 主要指标

| 指标 | 含义与分母 |
|---|---|
| `initial_instruction_requirement_coverage` | 初始明确表达的最终 material 要求 / 全部最终 material 要求；仅用要求可识别 threads，按要求计数，不是 session 等权平均 |
| `specificity_score`（上项内部） | 初始表达完整度：0 不兼容或最终要求不可识别，1 大部分验收要求缺失，2 核心目标明确但缺重要要求，3 仅缺次要验收细节，4 所有重要要求明确 |
| `material_requirement_emergence_rate` | 至少发生一次新增/变化 material 要求的 thread / 更新历史可识别 threads；独立新任务、旧要求修复不算演化 |
| `post_initial_material_update_basis.project_grounded_rate` | 用户后续表达的 project-grounded 新增/变化要求事件 / 用户后续新增/变化 material 要求事件 |
| `post_initial_material_update_basis.distribution` | 上述用户更新按 project-grounded、user-preference、mixed、unclear 分类的计数；偏好和 mixed 不能自动算作客观项目约束 |
| `observation_or_feedback_triggered_event_rate`（emergence 指标内部） | 有 explicit/strong 因果联系的观察或反馈触发用户更新 / 全部用户 material 更新事件；仅时间先后不算触发证据 |
| `terminal_requirement_discovery.earlier_discoverable_rate` | 最早可发现时间早于首次明确表达的晚期 grounded 更新 / 全部晚期 grounded 更新；包括非用户来源的新要求事件 |
| `terminal_requirement_discovery` 的 distributions | 晚期 grounded 更新的可发现状态及证据路径来源计数 |
| `literal_initial_instruction_satisfies_final_requirements_rate` | competent literal completion 可满足最终要求的 thread / 要求及该反事实可识别 threads；未知反事实另计，不当作 false |
| `agent_response_to_evolving_project_evidence` | 全部新增/变化 material 更新、晚期 grounded 更新的 agent 响应计数；另报既有要求修复数和无法判定更新类型的数量 |
| `cross_requirement_regression_rate`（上项内部） | 满足新要求但破坏既有要求的更新事件 / 全部新增/变化 material 更新事件 |
| `behavior_level_distribution` | scope 内、有项目推理机会且可分类的 episode 中，三类行为各自的比例；无机会和不可分类数量另报，不代表全部 episode 的无条件分布 |
| `cost_of_delayed_project_understanding` | 可判定延迟理解与非延迟理解 session 的成本对比；分组依据发现/识别/询问时间，而不是最终实现是否成功 |
| `evidence_to_correct_implementation_latency`（上项内部） | 延迟事件最早可发现证据 → 正确实现的 T 编号差和秒数；未解决/不可观察另计，负时间戳差记为缺失 |

**新增与修复的区别：** `requirement_change=new_requirement` 或 `changed_requirement` 进入演化统计；
`existing_requirement_correction` 是既有要求修复，独立计数；`unclear` 单独报告。
初始已明确的要求以及同一要求的重复发现，不再进入新要求发现指标。

### 行为三级分类

| 类别 | 含义 |
|---|---|
| `reactive_instruction_following` | 直接遵循/响应指令，没有解决重要不确定性或发现未述项目要求 |
| `instruction_scoped_sensemaking` | 在既定目标、scope 或验收范围内，诊断原因、消解重要歧义或比较方案 |
| `project_level_requirement_discovery` | 用项目证据发现未述的重要要求或下游影响，并实质改变计划、scope、策略或验收 |

第三级必须有 `requirement_novelty=new_material_requirement`，说明 `novel_requirement`、`material_change`，
并提供当前 episode 内的非用户来源证据。验证用户已提供的诊断、例行测试或修复自身实现错误，不自动算第三级。
无法判断新颖性时归为不可分类。

### 提前识别、提前完成与延迟理解

`first_explicit_turn` 是任何来源首次明确要求的时点；`first_user_requirement_turn` 是用户首次明确要求的时点，用户始终未提出时为 null。

| 响应类别 | 含义 |
|---|---|
| `anticipated_and_satisfied` | 识别和正确实现均严格早于用户首次明确表达 |
| `anticipated_then_satisfied_after_instruction` | 识别更早，但正确实现发生在用户表达当时或之后 |
| `autonomously_discovered_and_satisfied` | 用户始终未明确表达，agent 自主发现并满足 |
| `proactive_question_then_satisfied` | 有证据的针对性问题早于用户表达，随后满足要求 |
| `correctly_updated_after_new_evidence` | 新证据出现后正确更新实现 |
| `surface_symptom_patch` / `ignored_new_evidence` | 只修表面症状 / 忽略新证据 |
| `satisfied_new_but_regressed_existing` | 满足新要求但破坏已建立的要求 |
| `unclear_or_unresolved` / `not_applicable` | 不明确或未解决 / 不适用 |

延迟理解组要求晚期 grounded 新/变化要求存在更早证据，且识别未早于首次用户表达；没有用户表达时使用首次明确证据作为比较时点。
早期针对性询问可避免归为延迟。缺少足够 exposure 信息或更新历史不完整的 session 不混入已知非延迟组；已观察到延迟的 session 仍可进入延迟组。
`excluded_unknown_exposure_session_count` 报告无法分组的数量。

## 4. Study 2：表面指令与实际项目情况的错位

**Material mismatch** 指 competent agent 按初始表面指令和合理默认值执行，仍会与有证据支持的目标、约束或验收条件产生重要偏差。
普通实现错误、无害选择或用户后来真正改变目标，不自动算初始 mismatch；用户 belief 是证据支持的推断，不是直接读取心理状态。

| 指标 | 含义与分母 |
|---|---|
| `material_instruction_reality_mismatch_rate` | 存在 material mismatch 的 threads / actual situation 可识别 threads；不可识别数量另报，不当作无 mismatch |
| `mismatch_type_distribution`（上项内部） | 错误诊断、手段与目标冲突、遗漏重要要求、不可行/不兼容、抽象层级错误及其他错位的计数，可多标签 |
| `gap_driver.distribution` | mismatch 中用户 belief 的来源：偏好、经历、技术知识、项目知识、当前观察、外部建议、无说明依据的假设、mixed 或 unclear |
| `gap_driver.evidence_strength_distribution` | 来源证据为 explicit、strong inference、weak inference、insufficient 的计数；弱推断不应当作事实 |
| `belief_basis_scope_distribution`（gap_driver 内部） | belief 基于片面观察、较完整证据、非观察性偏好或无法判断的分布 |
| `partial_observation_belief_rate`（gap_driver 内部） | 片面观察型 belief / 信息基础可分类的 mismatch；分母含 partial、broadly-grounded、non-observational，排除 unclear 并另报 |
| `user_belief_identifiable_rate`（gap_driver 内部） | 用户 belief 可识别的 mismatch / 全部 mismatch |
| `mismatch_discoverability_and_route.initially_discoverable_rate` | 从初始项目状态可发现的 mismatch / 初始可发现性可判定的 mismatch；排除 unclear |
| `discoverable_before_user_explanation_rate`（上项内部） | 最早证据早于用户明确解释的 mismatch / 有用户明确解释的 mismatch |
| `mismatch_discoverability_and_route` 的 distributions | 初始可发现性、证据路径来源与 agent 发现方法的计数；来源和方法可能多选 |
| `literal_compliance_but_reality_failure_rate` | 字面要求可完成、但因 mismatch 无法解决实际情况的 threads / actual situation 可识别 threads；不是实际失败率，也不只以 mismatch 为分母 |
| `agent_gap_detection_and_response.user_mental_state_consideration_rate` | agent 明确考虑用户潜在目标/belief 的 mismatch / 全部 mismatch；普通代码检查不自动算 consideration |
| `proactive_consideration_or_detection_rate`（上项内部） | agent 在表面方案 commitment 及用户纠正/解释前已考虑或发现问题的 mismatch / 全部 mismatch |
| `proactive_reality_gap_detection_rate`（上项内部） | 满足主动条件且明确识别 gap 的 mismatch / 全部 mismatch |
| `response_pattern_rates`（上项内部） | 直接执行、早期澄清、早期发现并挑战各自 / 全部 mismatch；另有 mixed、unclear，因此三类不一定合计 100% |
| 三类 `evidence_to_*_latency`（上项内部） | 最早 mismatch 证据 → consideration、gap detection、实际问题被处理的 T 编号差/秒数；只汇总可观察且终点不早于起点者，其他另计 |
| `observed_resolution_by_agent_response` | 每类响应的 resolved/partial/unresolved/unknown 分布；resolved rate 的分母只含前三种，不含 unknown |
| `cost_of_faithful_execution_under_mismatch` | 存在先执行错位指令的 session，与没有这种先执行且至少一次早期澄清/挑战的 session 的成本对比；混合/不可分类另报 |

响应三类为 `follows_surface_instruction`、`clarifies_instruction_uncertainty`、`detects_reality_gap_and_resists`。
`surface_action_commitment_turn` 指实质采纳/执行表面方案，不包括用于验证前提的阅读、诊断测试或方案比较。
先执行再修复仍算先执行；澄清/挑战必须严格早于 commitment 才算早期处理。早期澄清和早期抵抗同时成立时，当前分类优先归为抵抗。

## 5. 成本、敏感性与运行完整性

### 成本字段

| 字段 | 含义 |
|---|---|
| `human_rework_lines` | `human_modified + human_removed`，人类修改/删除行数代理，不是严格因果返工量 |
| `linked_commit_deletions` | 关联 commit 的删除行数；session 内按 SHA 去重，但跨 session 可能共享 commit，不能当作独立工作量全局相加 |
| `committed_agent_code_share` | `agent_percentage / 100`，提交代码的 agent 归属比例，不是逐行纵向存活率 |
| `turn_count` / `tool_call_count` / `api_call_count` | 原始 coding session 的交互、工具调用和模型调用数量，不是此次标注调用量 |
| `total_tokens` | 数据集 input、output、cache creation、cache read 字段之和，不直接等于统一口径的账单费用 |
| `duration_seconds` | 原始 session 持续时间；标注模型 usage 保存在各 annotation 行的 `usage` 中 |

Study 1 的组间差值为“延迟组 − 非延迟组”；Study 2 为“先执行组 − 早期澄清/挑战组”。
应同时看两组 `n`、均值和中位数，不能将复杂任务带来的成本差异解释为因果效应。

### Study 1 额外敏感性统计

| 字段 | 含义 |
|---|---|
| `max` | 最大观测值 |
| `largest_value_share_of_total` | 最大值 / 全组总量，检查是否由单个 session 主导；仅在非负且总量为正时计算 |
| `mean_without_one_max` | 去掉一个最大值后的均值；仅作为诊断，原始数据不删除，少于两个观测时为 null |
| `trimmed_mean_10_percent` | 两端各去掉 floor(n/10) 个值后的均值；n<10 时为 null |
| `median_difference_delayed_minus_not_delayed` | 两组中位数之差 |
| `leave_one_session_out_mean_difference` | 每次从任一组去掉一个 session 后的均值差范围；`sign_changes` 表示范围同时包含正值和负值，提示结论方向敏感 |

这些是敏感性诊断，不是置信区间，也不替代保留全部数据的主统计。

### 运行完整性

`run_completeness` 给出 packet 总数、完成 session 数、待补 session 数和完成率。
Study 1 只有要求标注和全部行为 episodes 均完成，才算一个 session 完成；另报行为 episode 的缺口。
`run_meta` 保存模型、采样和处理参数；`prepare_meta.json` 还记录截断情况。

错误文件保留历史尝试，因此当前缺口以 `run_completeness` 为准，不以错误文件行数为准。
**完成率 100% 只表示结构有效的标注已齐备，不代表证据充分、标注正确或研究假设已得到支持。**
