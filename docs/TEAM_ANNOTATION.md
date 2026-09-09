# 中文／英文标注包 v3：三人 30 / 30 / 40

**本次统一使用 `annotation_release`。** 新页面顶部显示「中文／英文 · 精简表单 v3」及批次 ID。不要继续用旧下载文件：离线 HTML 内嵌数据，刷新不会更新。旧批次保留在 `annotation_archive/`，旧答案不迁移、不混收。

## 直接用浏览器标注

1. 下载仓库中的 **annotation_release.zip** 并解压，进入 `annotation_release/offline/`。也可下载整个仓库 ZIP 后进入同一路径。
2. 每个人打开自己的 HTML，无需安装 Python 或启动服务器：

| 人员 | 文件 | 数量 | 最终交付 |
| --- | --- | ---: | --- |
| A | `rater_a.html` | 30 | `submission_rater_a.json` |
| B | `rater_b.html` | 30 | `submission_rater_b.json` |
| C | `rater_c.html` | 40 | `submission_rater_c.json` |

3. 通读用户消息，逐轮展开 Agent／工具内容，填写选择题。所有内容随整个页面滚动，可切换通栏阅读。
4. 浏览器自动保存草稿；完成一条后点击「提交标注」。关闭前下载「备份全部进度」。换浏览器、电脑或文件路径时，导入同批次、同身份的备份。
5. 全部完成后点击「导出我的结果」，交付最新一份 submission JSON。backup 只用于恢复，不是正式交付文件。

GitHub 的 HTML 代码预览不能标注，需要下载后打开。不使用无痕窗口；浏览器禁止存储时，关闭前务必下载备份。同一身份只开一个标签页。

## 每条只需填写什么

**7 个基础选择项；有新需求时共 9 项。没有文字理由或项目概况，不逐事件填长表。**

| 部分 | 内容 |
| --- | --- |
| 需求 | 初始覆盖程度；有没有新需求；Agent 行为（多选） |
| 有新需求时 | 需求来源（单选）；首次出现的用户消息（从下拉列表选择） |
| 指令缺口 | 指令质量；主要原因（单选）；字面执行能否达成目标；Agent 主要处理方式 |

分类边界与例子见 [RUBRIC.md](RUBRIC.md)。没有足够证据时选「无法判断」，不需要补写解释。去掉文字理由减少工作量，但一致性仍需通过独立重复标注检验；本次 30/30/40 互不重叠，本身不能算标注员间一致性。

## 样本与轮数

从原始 `conversations.parquet` 重新筛选，保留中文／英文的用户交互。至少 8 次有效交互，其中至少 6 次有文字 Agent 回复；轮数不设上限，正文最多 180,000 字符、600 条事件。

有效交互是一组实质用户请求及其后可见的 Agent／工具活动。中间没有 Agent 活动的连续补充合并；固定模板、自动通知、技能／命令展开内容、纯确认和重复消息不计有效次数。界面保留这些源记录，但自动上下文默认折叠，并标明不计数原因。

T 是源事件证据编号，不是轮次。原始用户消息数与有效交互数分别显示。保留源 session 中全部 user、assistant、tool use、tool result 事件，不截取前 8 轮。源数据不保证项目从开始到结束均被收录，工具结果可能已截断；缺少记录不能判断 Agent 忽略要求。

[QUALITY_REPORT.md](QUALITY_REPORT.md) 提供批次分布；`source_manifest.json`、`candidate_audit.jsonl`、`trace_audit.json` 和每条 case 的 `interaction_quality` / `language_screen` 提供筛选与原文核验依据。

## 备用：每个人自己启动服务

需要 Python 3.10+，不需要第三方依赖。在含有 `annotate.py` 的目录执行；macOS/Linux 可把 python 换成 python3，Windows 可用 py -3。

```bash
python annotate.py verify
python annotate.py serve --rater rater_a
```

B/C 把 `rater_a` 换成 `rater_b` / `rater_c`。打开终端打印的完整 `http://127.0.0.1:8765/#token=...` 链接。Python 版离开前点击保存草稿或提交；数据保存在 `.local/rater_a/human.sqlite3`，下次运行同一命令继续。

```bash
python annotate.py status --rater rater_a
python annotate.py export --rater rater_a
```

已完成的结果写入 `submissions/submission_rater_a.json`。中途导出须加 `--allow-partial`。同一电脑同时运行多个身份时用不同 `--port`。离线 HTML 进度存浏览器，不能用 Python export 导出，需从 HTML 页面导出。

## 负责人汇总

收齐三份最新的 submission JSON，放入本包 `submissions/`，执行：

```bash
python annotate.py merge submissions/submission_rater_a.json submissions/submission_rater_b.json submissions/submission_rater_c.json --output-dir collected/final_v1
```

输出 `merged.json`、`annotations.jsonl`、`analysis.csv`、`summary.json`。会校验版本、批次、身份、30/30/40 归属、漏标、重复、样本指纹和答案一致性；成本从冻结样本重算。修订后用新输出目录如 `collected/final_v2`，不要输入同一人的多个版本。

自动计算用户消息、有效交互、工具/API 调用、token、时长，以及首次新需求之后的可见交互成本。不再逐事件统计新需求个数，该字段为 null。成本比较是描述性关联，不能估算“一开始说清楚会节省多少”。

个人答案、数据库和备份不要提交到 GitHub。需要继续旧批次时，用对应存档的运行代码；不要导入本次 v3。
