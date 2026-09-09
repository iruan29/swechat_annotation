# 有效交互样本质量报告

批次 ID：`a314b7e5cc5095ba62cdcf07172504d9435064cef4ae16575ac12877b6f75996`

合格候选池：113 条；按可见标注证据筛选后 seed=42 抽取 100 条，固定分配 30 / 30 / 40。

| 维度 | 最少 | 中位数 | 最多 |
| --- | ---: | ---: | ---: |
| 有效交互 | 8 | 12.0 | 41 |
| 原始用户消息 | 8 | 15.0 | 47 |
| 可见正文字符 | 30,836 | 147,630.5 | 219,874 |
| 可见事件 | 47 | 164.0 | 365 |

用户语言识别：en: 91；zh: 9。表单版本 human_simple_v4；7 项基础选择，有新需求时共 8 项。

覆盖 43 个仓库。Agent 分布：Claude Code: 99；OpenCode: 1。

这是经过可读性与多次实质交互筛选的子集，不能当作全量 SWE-Chat 的代表样本，也不宜直接用于跨 Agent 排名。仅筛选中文／英文用户交互。

## 计数规则

有效交互指一组实质性用户请求，随后有非空 assistant 回复或工具活动。连续发送且中间没有 Agent 活动的用户消息合并为一组。至少 8 次有效交互，其中至少 6 次有文字 assistant 回复；轮数无固定上限。

排除固定 review 模板会话、明显重复拆段、起始环境/自动消息和源顺序有歧义的会话。对实质 prompt 序列去重。纯确认、自动通知、技能/命令展开模板及重复 prompt 不计有效次数，原文仍保留。短命令如 commit、git status 是用户实际操作请求，可以计数；不要求每次请求都新增项目需求。

这些是可审计的启发式规则，不是人工意图标签。缺少响应不能推断 Agent 忽略要求，有工具活动也不证明要求已完成。判断需求是否新增、指令是否有问题仍由标注员完成。

## 可标注性门槛

在基础可读候选中，要求至少两段后续实质用户消息及可读的 Agent 回复，并有多种需求补充、原意纠正、理解差异、项目约束或澄清线索。API 错误文本不当作可读回复。选中的初始 prompt 与候选片段经过适用性检查，排除日志/模板主导和明显不适合软件项目分析的会话。

这是定向富集的研究样本，不能估计总体缺口发生率。关键词线索不是人工标签，不预先判定初始指令一定有错。selection_audit.jsonl 提供候选证据区间，selection_review.json 记录复核范围与排除原因；这些信息不在标注表中预填。

成本只统计整场会话。表单不再记录新需求位置，故不计算新需求之后的成本或新需求个数。

## 原文与追溯

- 全部保留源 session 的 user / assistant / tool use / tool result 事件及原编号，不只截取前 8 轮。
- 不保证项目从开始到结束的全部过程被源数据收录；thinking/system 不在界面，源工具结果可能已截断到 10KB。
- `source_manifest.json`：规则版本、边界、来源文件、候选排除统计与样本指纹。
- `candidate_audit.jsonl`：所有带 session 元数据的候选的首个排除原因，未做语义审查时的有效次数为 null。
- `assignment_inventory.csv`：逐条分配、两种轮数、长度与事件数。
- `assignments/*/cases.jsonl` 的 `interaction_quality`：每条 prompt 的分类原因、合并后的请求和响应 T 区间。
- `trace_audit.json`：本次发布额外用原始 parquet 逐条比对的报告；重建包后可运行 `python scripts/audit_human_traces.py` 重新生成。

## 已保留但不计有效请求的消息

```json
{
  "automatic_or_context": 253,
  "short_or_menu_choice": 20,
  "duplicate_prompt": 31,
  "acknowledgement_only": 54
}
```

旧批次存在模板凑轮或旧表单问题，保存在 `annotation_archive/`。本次请使用 `annotation_release`；旧备份不导入新包，结果不能混收。
