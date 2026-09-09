# 有效交互样本质量报告

批次 ID：`bc9d14a9b046716fe08f553b8e0a900521c89b4eee9e3916ba0d818cb1c08b7c`

合格候选池：117 条；seed=42 抽取 100 条，固定分配 30 / 30 / 40。

| 维度 | 最少 | 中位数 | 最多 |
| --- | ---: | ---: | ---: |
| 有效交互 | 8 | 10.0 | 41 |
| 原始用户消息 | 8 | 13.0 | 47 |
| 可见正文字符 | 21,731 | 101,659.5 | 149,338 |
| 可见事件 | 47 | 121.5 | 341 |

覆盖 49 个仓库。Agent 分布：Claude Code: 98；OpenCode: 2。

这是经过可读性与多次实质交互筛选的子集，不能当作全量 SWE-Chat 的代表样本，也不宜直接用于跨 Agent 排名。包含多种语言。

## 计数规则

有效交互指一组实质性用户请求，随后有非空 assistant 回复或工具活动。连续发送且中间没有 Agent 活动的用户消息合并为一组。至少 8 次有效交互，其中至少 6 次有文字 assistant 回复；轮数无固定上限。

排除固定 review 模板会话、明显重复拆段、起始环境/自动消息和源顺序有歧义的会话。对实质 prompt 序列去重。纯确认、自动通知、技能/命令展开模板及重复 prompt 不计有效次数，原文仍保留。短命令如 commit、git status 是用户实际操作请求，可以计数；不要求每次请求都新增项目需求。

这些是可审计的启发式规则，不是人工意图标签。缺少响应不能推断 Agent 忽略要求，有工具活动也不证明要求已完成。判断需求是否新增、指令是否有问题仍由标注员完成。

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
  "automatic_or_context": 210,
  "acknowledgement_only": 43,
  "short_or_menu_choice": 10,
  "duplicate_prompt": 17
}
```

旧 `annotation_release` 存在模板凑轮问题，保留作为历史批次。本次请使用 `annotation_valid_release`；旧备份不导入新包，结果不能混收。

## 本次发布的原文核验

100/100 条会话的所选事件与源 parquet 逐条一致。共有 1436 条原始用户消息；按每条原始消息切分，213 段之后没有可见 Agent/工具记录，涉及 70 条会话。这包含连续补充和自动记录等情况，不能视为 Agent 忽略请求。有效交互是另外合并、排除后计算的，每个样本均满足至少 8 次。
