# Study 1 / Study 2 流程审查

## 结论与范围

两项研究可以提供关于“要求演化、instruction–reality mismatch 与 agent 响应”的描述性证据。
不能提前保证支持原假设，也不能凭这些观察性关联得出“挑战用户指令导致更好结果”。
最初清理保留 requirements v5 / behavior v3；随后对 100-session pilot 的审查发现测量定义问题，
已升级为 requirements v6 / behavior v4。Study 2 保持 v8，不受本次修改影响。
输入清理会影响抽样和实际测量结果，所以使用新的输出目录，不承诺新旧数值不变。

## 已修复

### 100-session pilot 后的 v6/v4 修复

- 识别与满足时间分开：新增首次用户表达与主动询问时点，区分提前识别后实现、提前实现、自主发现；校验成功状态和时间一致性。
- 新/变化要求与既有要求纠错分开：后者单独计数，不再进入要求演化/晚期发现分母；初始明确与首次明确时点须一致。
- 第三级行为新增 requirement novelty 审计：需明确未述要求、实质变化及 episode 内证据；验证用户诊断不自动算新发现。
- 要求可识别性、演化历史可识别性与实现验证拆成三个独立字段；未知 literal 反事实不再归为 false。
- 延迟理解分组依据识别/询问时间，不再用是否满足来定义；缺失 exposure 信息不混入已知非延迟组。
- 成本报告增加最大值贡献率、去单个最大值均值、10% 截尾均值、中位数差及逐 session 留一敏感性，原始样本不删除。
- specificity ID partitions 和 inferable-before 改为派生字段，减少无意义的 repair；不为消除报错而猜测含糊 source。
- 版本升级后拒绝在旧 rubric 输出目录直接 resume 或 summarize；新命令使用独立 v6 目录，旧 pilot 不被改写。

这些修复已由离线回归测试覆盖，但**新版标注质量仍须运行后复核**。旧 95 个要求结果和 976 个行为结果
缺少新增证据字段，不能无模型复核地冒充新版结果。本次没有自动重跑标注，也没有修饰旧 pilot 的数值。

### 首轮运行与数据清理修复

| 问题 | 修复 |
|---|---|
| Study 1 无法确认是否全部行为 episode 标注完成，汇总可能混入旧版本或重复行 | 增加 session/episode 完整性统计；汇总按 rubric、packet 指纹和任务键筛选去重；全失败仍可报告缺口 |
| 同一 session 更换 packet/model 后，resume 仍可能复用旧判断 | 保存并核对输入指纹与 model；旧无指纹记录不直接复用，新命令使用独立目录 |
| 元数据合格不等于存在可用的多轮交互；续接摘要被当作新指令 | 抽样前扫描非 continuation 提示数，增加实际多轮检查；续接摘要只作为上下文 |
| 重复原始 T 编号使 evidence 引用与 episode key 有歧义 | 该 session 的保留事件重新编号，并保存原始编号映射；未擅自删除消息行 |
| 只标记丢弃事件，没有标记单条内容/提示/commit 被裁剪 | 补充截断标记和 packet diagnostics；文档不再宣称保留全部提示全文或严格 API 字符上限 |
| 要求/mismatch judge 仍可见 agent_percentage 等全局成果代理 | metadata 改为静态字段白名单；本地仍保留成本作后续确定性分析 |
| 同一 commit 经多个 checkpoint 关联可能重复累加删除量 | session 内按 commit SHA 去重；跨 session 共享归因问题仍需保留限制 |
| Study 1 全部行为历史前缀一次性展开、全部 futures 一次性提交 | 改为惰性生成与有界并发调度，降低全量内存压力；读取事件时提前做与 packet 相同的压缩 |
| HTTP session 未显式关闭 | 请求结束后关闭资源，避免高并发资源占用 |
| 异常逆序时间戳被计为零延迟 | 改作缺失，不制造虚假的即时解决 |
| 两项研究运行说明不对称，Study 2 部署说明与通用旧 pipeline 混杂 | 共用运行入口，补齐 Study 1 脚本、全量命令、单行试跑命令与统一 README |

## 仍需在试跑后审查，不应靠调 rubric 保证结论

1. **压缩造成测量误差。** 普通 user/assistant/tool 行均有字符上限，重要验收要求或反证可能位于被截掉的后半段。
   本地 100-session、seed=42、无上限样本经仅 prepare 验证：100 个 packet、976 个行为 episode，100 个 packet 的综合截断标记为 true，1 个 session 需要重编号。
   这不等于 100 个会话都不可用，但不能用“未丢事件”代替内容完整性。抽查原始事件与 packet，必要时做预算敏感性复标。
   单独提高 `max-packet-chars` 主要增加保留事件数量，**不会自动放宽每条事件的硬裁剪上限**。
2. **后见之明边界。** Study 1 要求阶段和 Study 2 需要完整会话来识别最终要求/稳定潜在目标，但后续证据不能证明 agent 当时已知道或可以知道。
   行为阶段隐藏未来文本仍不等于无选择偏差：其前缀从全局压缩 packet 中截取。
   `initial_state_discoverability` 是对当时可检查项目状态的推断，不是直接观察。
3. **用户改变目标不等于初始用户错误。** Study 1 可以记录真正的 goal change；Study 2 必须区分后来产生的新偏好与后来才揭示的稳定验收条件。
   普通实现错误、合理默认值可解决的模糊性、受允许的负面研究结论，都不应膨胀成 mismatch。
4. **LLM JSON 合法不等于测量可靠。** 部分事件/行为 null boolean 仍会被归为 false；v6 已不再将充分性缺失或 literal 反事实 null 归为 false，并将部分字段由时间与 ID 确定性派生。
   应对照原始证据复核 false、unclear、低置信度、validation repair 样本，尤其不要将结构校验通过率当作标注准确率。
5. **分母与排除有选择性。** Study 1 覆盖率按要求可识别性筛选，演化率按更新历史可识别性独立筛选；行为指标只用有机会且可分类 episodes；Study 2 mismatch 率只用 actual situation 可识别 threads。
   unknown、不明确、失败及长会话的比例必须报告。成本比较中的 unexposed 也不等于“已证明理解完美”。
6. **成本不是因果效应。** 复杂任务自然可能有更多 turn、要求变化与返工；同 repo/session 内结果相关，commit 可跨 session。
   工程成本是整场 session 的代理，而非单个错位事件之后产生的净成本。已解决样本的 latency 还受到未解决事件排除的影响。
7. **统计推断尚未实现。** Study 1/2 目前只有点估计、计数、均值和中位数，没有 CI 或显著性检验。
   正式论文需要人工复核、独立复标与一致性报告，并在需要区间时考虑 session/repository 聚类；不能套用旧 README 的 bootstrap 声明。
8. **标注成本与 200 并发风险。** Study 1 全量是 62,066 个名义任务，不是 4,384 次请求。上下文长度、repair、重试与服务端配额决定实际成本。
   当前并发上限不是全局 RPM/TPM 限流器；先用 100-session 试跑估计失败率、请求 usage 与可分类比例。

## 数据口径

本地 sessions 总数 5,851；旧元数据多轮无上限筛选得到 4,442，旧 prepare 实际得到 4,393 个有 user_prompt 的 packet。
增加实际非续接多轮检查后为 **4,384**，对应 **57,682** 个行为 episode。
这是“沿用元数据筛选后加有效性检查”的总体，不是“完全按事件数重新定义多轮”的更大总体。
使用 `python scripts/count_samples.py` 重算；完整流程、指标分母与命令以 [README.md](README.md) 为准。
