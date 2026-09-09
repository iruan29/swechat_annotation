# 三人 SWE-Chat 标注包：30 / 30 / 40

本目录可以单独放到 GitHub，也可以下载 ZIP 后解压使用。**推荐双击离线 HTML：标注员只需要浏览器，不需要 Python、服务器或安装依赖。** 最终汇总负责人使用 Python 3.10+。

100 条样本已冻结，每条至少 **8 次有效用户交互，轮数无固定上限**，正文完整保留所选事件类型。每个人处理不同样本：

| 分工 | 固定身份 | 数量 | 交付文件 |
| --- | --- | ---: | --- |
| 第一人 | `rater_a` | 30 | `submission_rater_a.json` |
| 第二人 | `rater_b` | 30 | `submission_rater_b.json` |
| 第三人 | `rater_c` | 40 | `submission_rater_c.json` |

负责人把姓名与 a/b/c 对应好即可，不需要改代码或重分样本。分工互不重叠，总计 100 条；此设计不能计算标注员间一致性。建议开始前一起讨论标注口径，勿把讨论结果当成独立复标。

## 当前批次的交互记录说明

本次使用 `annotation_valid_release` 新批次。旧 `annotation_release` 留作历史存档：其中固定 review 模板和消息段拆分导致原轮数虚高，请勿继续使用旧批次做本次标注。旧备份请自行保留；新旧 `package_id` 不同，不能导入或混收。

**有效交互 = 一组实质性用户请求 + 后续可见 Agent 回复或工具活动。** 中间没有 Agent 活动的连续用户补充合并为一组。纯确认、自动续接、工具加载/后台通知、技能与命令展开模板、重复 prompt 不计数，但原文全部保留；界面会显示“有效交互 N”或不计数原因。请求后的活动不等于成功完成要求。原始用户消息数单独显示，不能与有效交互数混用。

筛选要求至少 8 次有效交互，其中至少 6 次有文字 assistant 回复；不设轮数上限。为控制阅读量，所选类型正文为 1,000–150,000 字符、最多 600 条事件。排除固定 review 模板 session、重复拆段、起始环境/自动消息与顺序不明确的记录，对实质 prompt 序列去重后 seed=42 无放回抽 100 条。所有规则是可复查的启发式，不是对用户意图的人工金标准。

每条的计数与证据区间见 `assignments/*/cases.jsonl` 中的 `interaction_quality`；来源参数见 `source_manifest.json`，批次分布见 `QUALITY_REPORT.md`，原文逐条核验见 `trace_audit.json`。这是偏向可读、多次实质交互的子集，不代表 SWE-Chat 全体分布。数据包含多种语言；不要据语言猜测用户能力或文化背景。

所有内容随页面自然向下延伸，不再有对话或表单的小范围滚动框。桌面默认并排显示对话与标注，点击“切换为通栏阅读”可改为上下排列。顶部快捷导航可跳到对话、表单、样本列表和页面顶部；窄屏自动上下排列。样本编号卡片和进度条显示完成情况，HTML 保留每段“未收录响应”的提示。

本界面没有进一步裁剪所选正文，但源数据卡说明 `tool_result` 内容可能已截断到 10KB；不能称为原始所有事件的无损完整转录。

## 推荐：双击 HTML，直接在浏览器中标注

1. 在 GitHub 点击 **Code → Download ZIP**，解压后进入 `annotation_valid_release/offline/`。如果拿到的是独立标注包 ZIP，直接进入 `offline/`。
2. 每个人用 Chrome / Edge / Firefox 打开自己的文件：

| 人员 | 双击打开 | 数量 |
| --- | --- | ---: |
| 第一人 | `rater_a.html` | 30 |
| 第二人 | `rater_b.html` | 30 |
| 第三人 | `rater_c.html` | 40 |

3. 填写内容会自动保存为**草稿**；完成一条后点击「提交标注」。无需运行 serve，也不会向服务器发送会话或答案。
4. 关闭前点击「备份全部进度（含草稿）」下载 JSON。换电脑、浏览器或文件路径时，打开同一个人的 HTML，然后「导入进度」。浏览器本地保存不是随 HTML 文件一起携带的，移动文件后看不到进度时请导入备份。
5. 全部完成后点击右上角「导出我的结果」，将 `submission_rater_a.json`（b/c 同理）交给负责人。**backup 是进度备份，submission 才是正式交付。**

GitHub 的 HTML 文件预览页只显示代码，不会执行标注页面，需先下载到本地。不要使用无痕窗口长期标注；如果浏览器禁止存储，页面会提示仅保存在内存，此时关闭前必须下载备份。每个人只开一个标注标签页，避免版本冲突。

离线版与下面的 Python 版使用同一批样本、身份和提交 JSON 格式。已有 Python 版的已提交结果可导入 HTML 继续修订；未提交的数据库草稿不会自动转移。离线版进度放在浏览器，不会出现在 Python 版的 status/export 命令里，请从 HTML 页面导出。

负责人收齐三个 submission JSON 后，直接使用本文后面的 merge 命令，汇总流程不变。

## 备用方式：Python 本地服务

以下 serve/export/status 命令仅适用于 Python 版；使用上面的 HTML 版无需执行。

## 每个人第一次使用

1. 从负责人指定的 GitHub 仓库下载 ZIP 并解压，或 `git clone 仓库URL`。三个人使用同一批次；不要自己抽样或修改 `assignments/`。
2. 在包含 `annotate.py` 的目录打开终端。
3. 检查 Python 与样本完整性：

```bash
python --version
python annotate.py verify
```

macOS / Linux 若 `python` 不存在，将以下命令的 `python` 换成 `python3`；Windows 可换成 `py -3`。版本需 ≥3.10。

## 第一人：30 条

```bash
python annotate.py serve --rater rater_a
```

打开终端打印的完整 `http://127.0.0.1:8765/#token=...` URL。页面自动选择 `rater_a`，只显示你的 30 条，不需要再输入 ID。

全部提交后，点击页面右上角「导出我的结果」，将下载的 **`submission_rater_a.json`** 交给负责人。也可以在终端运行：

```bash
python annotate.py status --rater rater_a
python annotate.py export --rater rater_a
```

文件写到 `submissions/submission_rater_a.json`。

## 第二人：30 条

```bash
python annotate.py serve --rater rater_b
# 完成后在新终端执行，或 Ctrl+C 停止服务后执行：
python annotate.py export --rater rater_b
```

页面自动绑定 `rater_b`。交付下载的 JSON 或 `submissions/submission_rater_b.json`。

## 第三人：40 条

```bash
python annotate.py serve --rater rater_c
python annotate.py export --rater rater_c
```

页面自动绑定 `rater_c`。交付下载的 JSON 或 `submissions/submission_rater_c.json`。

三个人在各自电脑都可以用 8765 端口。同一台机器同时开多份服务时，可分别用 `--port 8766`、`--port 8767`。不要为同一身份同时启动多个服务。

## 如何读与标

- 左侧默认展示**全部用户 prompt**，Agent / 工具按轮折叠；展开后才加载正文。没有“第一页只显示四轮”的限制。
- 有效交互按上面的请求与活动分组计算；原始用户消息数另外展示。T 是源事件证据编号，可能跳号，不是交互次数。自动续接上下文保留，但不计为真实用户请求。
- 样本保留源 session 中全部 user / assistant / tool use / tool result 事件，不截取前几轮、不截断正文。thinking / system 等事件不在阅读界面；`trace_scope` 记录源事件数量及类型。数据集本身不一定包含项目真正从开始到结束的全部过程，不能把 session 完整提取等同于项目完整记录。
- 一条会话一张表：**13 个基础必填字段**，加可选备注；每个需求事件另加 8 个字段。无事件为 13 项，一个事件为 21 项，两个为 29 项。同一要求的重复提及不新建事件。
- 基础部分：项目目标与可判断程度（2 项）；需求覆盖、更新、行为、证据与理由（5 项）；指令质量、原因、字面可行性、Agent 处理、证据与理由（6 项）。
- 初始遗漏、真正新增目标、旧要求修复要分开；用户局限需要证据，不猜测文化或能力。证据不足选「无法判断」，写明原因。
- 证据用左侧 T 编号，点击可复制，多个编号用逗号分隔。点击「提交标注」前阅读完整会话。
- 项目详情、Agent 分类与例子见 [RUBRIC.md](RUBRIC.md)。本包所有操作使用本 README 的 `annotate.py` 命令。
- 用户轮数、工具 / API 调用、token 与时长自动算；不要人工估计「一开始说清楚会节省多少」。

## Python 版：中断、继续与备份

- 表单不会自动保存。离开前点击「保存草稿」或「提交标注」。未保存内容关闭浏览器会丢失，页面会提示。
- `Ctrl+C` 停止服务；下次运行**同一身份、同一目录**的 serve 命令即可继续。启动 token 每次变化，请打开新打印的 URL。
- 草稿和已提交结果在 **`.local/rater_a/human.sqlite3`**（b/c 同理），不在浏览器缓存。不要删除 `.local`。
- 要换电脑：先停止服务，再拷贝整个标注包（包含隐藏目录 `.local`）到新电脑，继续相同命令。也可以停止服务后备份整个 `.local` 目录；恢复时放回**同批次**标注包。
- 导出 JSON 只包含已提交结果，不含草稿，不是完整进度备份。中途 CLI 导出需显式添加 `--allow-partial`；页面中途导出会提示未完成数量。
- 提交后允许修订；重新保存成草稿的样本会暂时退出统计，必须再次提交。修改完成后重新导出，将**最新一个** JSON 交给负责人。
- 不需提交数据库或个人结果到 GitHub，`.gitignore` 已排除 `.local/`、`submissions/`、`collected/`。个人结果通过你们约定的文件渠道交付。

## 负责人：回收并汇总

将三份最新的 JSON 放到本包的 `submissions/` 目录：

```text
submissions/
  submission_rater_a.json
  submission_rater_b.json
  submission_rater_c.json
```

执行（Windows 也可直接使用这一行）：

```bash
python annotate.py merge submissions/submission_rater_a.json submissions/submission_rater_b.json submissions/submission_rater_c.json --output-dir collected/final_v1
```

命令会检查批次 ID、30/30/40 归属、样本指纹、口径版本、重复项、漏标、证据编号、答案合法性及完成状态；从冻结样本重新计算成本，而不是信任用户 JSON 中的统计数字。任何一项不符都会报错，且不生成貌似完整的汇总。

生成：

| 文件 | 内容 |
| --- | --- |
| `merged.json` | 三人全部有效标注与统一统计，保留标注员和证据 |
| `annotations.jsonl` | 每行一条完整标注，便于分析 |
| `analysis.csv` | 每样本主要分类与成本，可用 Excel / pandas 打开 |
| `summary.json` | 完成数量、有无晚出现需求及指令质量的成本比较 |

同一个输出目录不能覆盖。收到修订文件后只保留该人的最新 JSON，再用 `--output-dir collected/final_v2` 重做汇总；不要同时输入同一人的多个版本。

中期检查允许只收到部分文件：

```bash
python annotate.py merge submissions/submission_rater_a.json --allow-partial --output-dir collected/interim_v1
```

中期结果明确标记未完成及缺失样本，不冒充 100 条最终结果。成本差异只是描述性关联；没有同任务的实验对照，不能估算清晰初始指令的因果节省。

## 负责人：放到 GitHub

将**这个独立包的内容**作为仓库内容（或放在已有仓库的一个独立目录）。它仅包含运行代码、前端、100 条样本、分配表和指南，不需要整个研究仓库的 `.env`、数 GB parquet、历史输出或数据库。

推送前运行 `python annotate.py verify`。负责人给三个人同一个仓库版本，并确认各自身份。批次由 `assignments.json` 的 `package_id` 标识；发出后不要改分配表和样本。如需要新一批数据，应重新打包并单独通知，不能混收两批结果。

数据来源说明见 [DATA_NOTICE.md](DATA_NOTICE.md) 和原始数据卡 [DATA_SOURCE.md](DATA_SOURCE.md)。
