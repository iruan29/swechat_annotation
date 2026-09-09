"""Generate self-contained HTML files. Embedded traces cannot escape the data script."""
from __future__ import annotations

import json
from pathlib import Path

from . import human_simple as simple
from .human_schema import blank
from .human_team import load_bundle, RATERS


def generate(root: Path) -> list[Path]:
    config, cases = load_bundle(root)
    assets = Path(__file__).parent / 'human_web'
    base = (assets / 'index.html').read_text(encoding='utf-8')
    css = (assets / 'style.css').read_text(encoding='utf-8')
    app = (assets / 'app.js').read_text(encoding='utf-8')
    offline = (assets / 'offline.js').read_text(encoding='utf-8')
    base = base.replace('<link rel="stylesheet" href="/style.css"><script src="/app.js" defer></script>',
                        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; object-src \'none\'; base-uri \'none\'; form-action \'none\'"><style>' + css + '</style>')
    base = base.replace('<main>', '''<div class="offline-tools"><p id="offline-notice">离线版：无需服务器，填写后自动保存到当前浏览器。关闭前建议「备份全部进度」；换电脑、移动文件或清理浏览器后，可用备份恢复。最终交付请点击右上角「导出我的结果」。</p><button id="backup-progress">备份全部进度（含草稿）</button><label>导入进度 <input id="restore-progress" type="file" accept=".json,application/json"></label></div><main>''')
    base = base.replace('旧版项目仍保留原三阶段规则。', '只需打开自己的 HTML 文件，不需要 Python。')
    directory = root / 'offline'
    directory.mkdir(exist_ok=True)
    paths = []
    for rater in RATERS:
        payload = dict(package_id=config['package_id'], rater=rater, version=simple.VERSION,
                       cases=[cases[sid] for sid in config['assignments'][rater]], schema=simple.schema(),
                       blank=blank(simple.schema()), rubric=simple.RUBRIC)
        data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
        scripts = '<script id="offline-data" type="application/json">' + data + '</script>\n<script>' + offline.replace('</script', '<\\/script') + '\n</script>\n<script>' + app.replace('</script', '<\\/script') + '\n</script>'
        html = base.replace('<title>SWE-Chat 人工标注台</title>', f'<title>SWE-Chat · {rater} · 离线标注</title>')
        is_effective = all(cases[sid].get('interaction_quality') for sid in config['assignments'][rater])
        label = '中文／英文 · 精简表单 v3' if simple.VERSION == 'human_simple_v3' else '有效交互新版' if is_effective else '历史批次 · 请核对筛选口径'
        banner = f'<div id="batch-banner" class="offline-tools"><strong>{label} · {rater} · {len(payload["cases"])} 条</strong><p>批次：{config["package_id"][:12]} · 原始用户消息数与有效交互数分别展示。</p></div>'
        html = html.replace('<body id="page-top">', '<body id="page-top">' + banner)
        html = html.replace('</body>', scripts + '\n</body>')
        path = directory / f'{rater}.html'
        path.write_text(html, encoding='utf-8')
        paths.append(path)
    (directory / 'README.md').write_text('''# 双击 HTML 标注，无需 Python

下载仓库 ZIP 并解压，然后打开自己的文件：

- `rater_a.html`：30 条
- `rater_b.html`：30 条
- `rater_c.html`：40 条

用 Chrome、Edge 或 Firefox 打开。GitHub 的代码预览页不会运行 HTML，需要先下载。
填写后自动保存为草稿；完成每条后点击“提交标注”。关闭前下载“备份全部进度”，它包含草稿和已提交答案。换电脑、浏览器或文件路径时，打开同一人的 HTML 并“导入进度”。备份也可以导入服务器版导出的 submission JSON，继续修订已提交答案；服务器数据库里的未提交草稿不会自动转移。

全部完成后点击右上角“导出我的结果”，将 `submission_rater_a.json`（b/c 同理）交给负责人。不要把 backup 文件当成正式提交。离线版与 Python 版的提交 JSON 使用相同格式，负责人继续使用上一级 README 的 merge 命令。

不要用无痕窗口长期标注；浏览器拒绝存储时会明确提示“仅在本页内存中”，此时必须下载备份。一次只开同一人的一个标签页，避免版本冲突。自动保存不等于提交，只有点击提交后的样本计入最终交付。
''', encoding='utf-8')
    print('已生成离线 HTML：' + ', '.join(str(path) for path in paths))
    return paths
