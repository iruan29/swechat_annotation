# Study 1 Pilot Results

- 数据完整性
  - Requirement annotation 完成率：**100.0%**（抽取的所有 session 都完成了 requirement 标注）
  - Behavior annotation 完成率：**100.0%**（所有识别出的 user-instruction episodes 都完成了行为标注）
  - Requirement annotation 错误率：**0.0%**（requirement 阶段没有 pipeline 或 validation error）
  - Behavior annotation 错误率：**0.0%**（behavior 阶段没有 pipeline 或 validation error）
  - Evidence-sufficient thread rate：**87.5%**（task threads 中具有足够证据、可以进入 requirement 主指标计算的比例）
  - Evidence-insufficient thread rate：**12.5%**（由于缺少最终实现、测试或完成证据而被排除的 task-thread 比例）
  - Requirement judge 平均置信度：**89.3%**（LLM judge 对 requirement annotations 的平均自评置信度）
  - Requirement judge 中位置信度：**89.5%**（一半 annotation 的置信度高于该值，另一半低于该值）

- 初始 instruction 的充分性
  - Initial requirement coverage：**47.6%**（最终 material requirements 中已经被初始 instruction 明确表达的比例）
  - Initial requirement omission rate：**52.4%**（最终 material requirements 中没有被初始 instruction 明确表达的比例）
  - 平均 initial specificity：**58.9%**（平均 specificity score 相对于满分的比例，衡量初始指令界定最终验收要求的完整程度）
  - 中位 initial specificity：**50.0%**（中位 specificity score 相对于满分的比例）
  - Literal initial-instruction sufficiency：**21.4%**（仅字面完成初始 instruction 就足以满足最终 requirements 的 task-thread 比例）
  - Literal initial-instruction insufficiency：**78.6%**（仅字面完成初始 instruction 仍不足以满足最终 requirements 的 task-thread 比例）
  - Material requirement emergence：**78.6%**（在初始 instruction 之后出现至少一个 material requirement update 的 task-thread 比例）
  - No material requirement emergence：**21.4%**（没有观察到后续 material requirement update 的 task-thread 比例）

- Substantive-thread sensitivity analysis
  - Substantive-thread share：**85.7%**（证据充分 threads 中至少包含一个 final material requirement 的比例）
  - Empty-thread share：**14.3%**（证据充分但没有 final material requirement 的 threads 比例）
  - Material requirement emergence（排除 empty threads）：**91.7%**（只在包含 final material requirement 的 threads 中，出现后续 material update 的比例）
  - Literal initial-instruction sufficiency（排除 empty threads）：**8.3%**（只在包含 final material requirement 的 threads 中，字面完成初始指令即可满足最终要求的比例）

- User-articulated material updates 的 requirement basis
  - Project-grounded：**35.0%**（更新由代码、接口、测试、运行环境、依赖或项目功能约束决定）
  - User preference：**50.0%**（更新主要来自用户个人偏好、工作方式或多个可行方案之间的主观选择）
  - Mixed：**15.0%**（更新同时包含项目客观约束与用户主观偏好，且二者无法合理分离）

- 用户提出 material update 的 trigger
  - Spontaneous user revision：**50.0%**（用户主动修改或补充要求，没有可观察到的外部反馈直接触发）
  - Agent explanation or proposal：**25.0%**（agent 的解释、建议或方案促使用户进一步明确或修改要求）
  - Review or external feedback：**20.0%**（代码审查、外部人员意见或其他外部反馈促使用户更新要求）
  - Test or CI feedback：**5.0%**（测试或 CI 结果促使用户更新要求）
  - Observation-or-feedback triggered：**50.0%**（有明确或强证据表明 user update 是由 agent、review、test 或其他可观察反馈触发的比例）
  - Explicit causal-link strength：**95.0%**（user update 与其 trigger 之间存在用户明确说明的因果联系）
  - Strong causal-link strength：**5.0%**（虽然用户没有完全明说，但证据强烈支持 trigger 与 update 之间存在因果联系）

- 全部 post-initial material updates 的 event type
  - User goal change：**35.7%**（用户改变目标、scope 或可接受成果）
  - Environment constraint discovery：**25.0%**（代码、运行环境、依赖或接口暴露新的约束）
  - Correction：**21.4%**（证据表明先前理解或实现存在实质错误）
  - Requirement revelation：**17.9%**（原本未表达的 material requirement 在后续交互中被明确）

- 全部 post-initial material updates 的 articulation source
  - User：**71.4%**（material update 首先由用户明确表达）
  - Tool：**10.7%**（material update 首先由工具、测试或执行结果明确暴露）
  - Repository：**10.7%**（material update 首先由代码或项目结构明确暴露）
  - Agent：**7.1%**（material update 首先由 agent 的推理或说明明确表达）

- Late project-grounded requirement 的可发现性
  - Earlier-discoverable：**21.4%**（后续 project-grounded requirement 在正式表达前已经存在足够证据，可由 competent agent 合理推断）
  - Not earlier-discoverable：**78.6%**（现有证据不足以证明该 requirement 可以在正式表达前被发现）
  - Became discoverable later：**85.7%**（决定性项目证据是在交互后期才出现的 late project-grounded requirement 比例）
  - Explicit initially：**14.3%**（相关 project requirement 已经由初始信息明确支持，但在事件记录中于后续再次出现的比例）
  - Earlier-discoverable requirements anticipated by agent：**66.7%**（可提前发现的 requirements 中，agent 在用户正式表达前已经识别并满足的比例）
  - Earlier-discoverable requirements with delayed understanding：**33.3%**（可提前发现的 requirements 中，agent 没有及时识别或 elicitation、后来才响应的比例）

- Requirement discovery evidence-path source
  - Repository：**26.9%**（discovery evidence path 中来自代码、配置或项目结构的证据比例）
  - Initial instruction：**23.1%**（来自初始用户指令的证据比例）
  - Agent inference：**15.4%**（来自 agent 明确推理的证据比例）
  - Review：**15.4%**（来自 review 或外部审查的证据比例）
  - User update：**11.5%**（来自用户后续表达或修正的证据比例）
  - Observed output：**3.8%**（来自实际运行输出的证据比例）
  - Test or CI：**3.8%**（来自测试或 CI 结果的证据比例）

- Agent response to all material updates
  - Anticipated and satisfied：**25.0%**（agent 在 requirement 被正式表达前已经识别并正确满足）
  - Correctly updated after new evidence：**60.7%**（新 requirement 或证据出现后，agent 正确调整了理解或实现）
  - Unclear or unresolved：**14.3%**（证据不足以确认响应，或 requirement 在观察窗口结束时仍未解决）
  - Surface symptom patch：**0.0%**（只修补表面症状、没有处理实际 requirement 的比例）
  - Ignored new evidence：**0.0%**（忽略新 requirement 或与其冲突证据的比例）
  - Satisfied new but regressed existing：**0.0%**（满足新 requirement 但破坏已有 requirement 的比例）
  - Cross-requirement regression：**0.0%**（material updates 中造成其他既有 requirement regression 的比例）

- Agent response to late project-grounded updates
  - Anticipated and satisfied：**50.0%**（后续 project-grounded updates 中，agent 在明确表达前已经发现并满足的比例）
  - Correctly updated after new evidence：**35.7%**（后续项目证据出现后，agent 正确调整的比例）
  - Unclear or unresolved：**14.3%**（后续 project-grounded update 未解决或证据不足的比例）

- Behavior episode scope and evidence
  - In-scope episode rate：**79.7%**（全部 user-instruction episodes 中属于实际工程任务、可以进行行为判断的比例）
  - Out-of-scope episode rate：**20.3%**（问候、确认、注入内容或纯状态消息等不属于有效任务 episode 的比例）
  - Classification-sufficient rate：**92.7%**（in-scope episodes 中具有足够证据进行行为分类的比例）
  - Classification-insufficient rate：**7.3%**（in-scope episodes 中由于截断或缺少响应证据而无法可靠分类的比例）
  - Project-reasoning opportunity rate：**49.1%**（in-scope episodes 中存在重要歧义、隐藏约束、冲突、下游影响或 literal compliance 风险的比例）
  - No project-reasoning opportunity rate：**50.9%**（in-scope episodes 中没有明显项目级推理机会的比例）
  - Opportunity classification coverage：**96.3%**（存在 project-reasoning opportunity 的 episodes 中可以可靠分类行为模式的比例）
  - Opportunity unclassified rate：**3.7%**（存在 project-reasoning opportunity 但证据不足以判断 agent 行为的比例）

- Behavior mode（以可分类且存在 project-reasoning opportunity 的 episodes 为分母）
  - Instruction-scoped sensemaking：**69.2%**（agent 识别并解决重要不确定性，但仍在用户明确 instruction 的目标和 scope 内行动）
  - Reactive instruction following：**23.1%**（虽然存在 reasoning opportunity，agent 仍主要按表面 instruction 执行，没有充分解决重要不确定性或发现隐藏 requirement）
  - Project-level requirement discovery：**7.7%**（agent 使用项目证据发现未表达的 material requirement 或 downstream impact，并实质改变计划、策略、scope 或验收标准）
  - Non-reactive handling：**76.9%**（存在 reasoning opportunity 时，agent 至少进行了 instruction-scoped sensemaking 或 project-level requirement discovery 的比例）

- Behavior mode（以所有可分类的 in-scope episodes 为分母）
  - Reactive instruction following：**60.8%**（包括没有明显 reasoning opportunity 的常规执行 episode 在内，agent 采用 reactive 模式的比例）
  - Instruction-scoped sensemaking：**35.3%**（全部可分类 in-scope episodes 中进行 instruction 范围内 sensemaking 的比例）
  - Project-level requirement discovery：**3.9%**（全部可分类 in-scope episodes 中进行项目级 requirement discovery 的比例）

- Opportunity episodes 中的原子行为指标
  - Important uncertainty identified：**84.6%**（agent 明确识别了可能影响正确实现的重要未知、歧义或冲突）
  - Instruction scope preserved：**92.3%**（agent 在解决不确定性时仍保持用户明确指定的 material goal 和 scope）
  - Project evidence used：**65.4%**（agent 使用 repository、documentation、test、execution 或 prior requirement 等项目证据）
  - Proactive before explicit correction：**53.8%**（agent 在用户明确纠正或补充 requirement 之前就开始处理相关问题）
  - Material plan, strategy, scope, or acceptance affected：**50.0%**（agent 的推理实际改变了计划、实现策略、scope 或验收方式）
  - Unstated material requirement or downstream impact identified：**7.7%**（agent 明确识别出用户没有表达的 material requirement 或重要 downstream impact）

- Opportunity episodes 中的 resolution/detection method
  - Repository evidence：**76.9%**（agent 通过代码、配置或项目结构解决不确定性；该组为多选指标）
  - Execution evidence：**30.8%**（agent 通过测试、运行结果或错误信息解决不确定性；该组为多选指标）
  - Alternative comparison：**19.2%**（agent 比较多个方案或解释以解决不确定性；该组为多选指标）
  - User question：**7.7%**（agent 向用户提出有针对性的问题以解决重要不确定性；该组为多选指标）
  - Prior requirement：**7.7%**（agent 使用先前已建立的 requirement 或上下文解决不确定性；该组为多选指标）

- Cost of delayed project understanding
  - Delayed-understanding exposure rate：**12.5%**（eligible sessions 中存在可提前发现但未被及时识别或 elicitation 的 project-grounded requirement 的比例）
  - No-delayed-understanding rate：**87.5%**（eligible sessions 中没有观察到上述 delayed-understanding exposure 的比例）
  - API-call relative difference：**+1252.3%**（delayed group 相对于 no-delayed group 平均 API-call 数的描述性差异）
  - Tool-call relative difference：**+1348.8%**（delayed group 相对于 no-delayed group 平均 tool-call 数的描述性差异）
  - Token relative difference：**+2045.2%**（delayed group 相对于 no-delayed group 平均 token 使用量的描述性差异）
  - Duration relative difference：**+994.2%**（delayed group 相对于 no-delayed group 平均会话时长的描述性差异）
  - Turn-count relative difference：**+77.5%**（delayed group 相对于 no-delayed group 平均 turn 数的描述性差异）
  - Human-rework relative difference：**-100.0%**（delayed group 相对于 no-delayed group 平均 human-modified/removed lines 的描述性差异）
  - Linked-commit-deletion relative difference：**-100.0%**（delayed group 相对于 no-delayed group 平均 linked-commit deletions 的描述性差异）
  - Committed-agent-code-share relative difference：**-100.0%**（delayed group 相对于 no-delayed group 平均 agent-authored committed-code share 的描述性差异）
  - Delayed-event correct-implementation observed rate：**0.0%**（delayed requirement events 中能够观察到正确实现时间点的比例）
  - Delayed-event unresolved-or-unobservable rate：**100.0%**（delayed requirement events 中最终未解决或无法从现有证据确认正确实现的比例）

- 解释限制
  - Delayed group 占比：**12.5%**（cost comparison 的 exposed group 极小，因此极端百分比主要反映单个长会话，不能解释为 delayed understanding 的因果效应）
  - User-preference share：**50.0%**（一半 user updates 属于主观偏好，说明 agent 不应该把所有后续变化都视为本应提前猜到的隐藏项目要求）
  - Earlier-discoverable share：**21.4%**（只有少数 late project-grounded requirements 有证据表明可以提前发现，研究结论应聚焦有可用项目证据的 mismatch，而不是要求 agent 预测未来信息）
  - Project-level discovery rate：**7.7%**（agent 经常进行局部 sensemaking，但很少将项目证据上升为未表达的 project-level requirement）
