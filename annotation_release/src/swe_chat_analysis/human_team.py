"""Portable annotation assignments, JSON delivery, and validated collection (stdlib only)."""
from __future__ import annotations

import argparse
import csv
from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import random
import secrets
import shutil
import sys
import zipfile

from .human import HumanProject, digest, handler
from . import human_simple as simple
from .io import read_jsonl, write_jsonl

FORMAT = 'swe_chat_team_v1'
RATERS = ('rater_a', 'rater_b', 'rater_c')
COUNTS = (30, 30, 40)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'非法数值 {value}')))


def package_identity(config):
    return digest({key: config[key] for key in ('format', 'rubric_version', 'assignments', 'case_fingerprints')})


def load_bundle(root):
    config = read_json(root / 'assignments.json')
    if config['format'] != FORMAT or config['rubric_version'] != simple.VERSION or package_identity(config) != config['package_id']:
        raise ValueError('分发包版本或分配校验值不匹配')
    if tuple(config['assignments']) != RATERS:
        raise ValueError('标注员列表不匹配')
    all_cases = {}
    for rater, count in zip(RATERS, COUNTS):
        ids = config['assignments'][rater]
        if len(ids) != count or len(set(ids)) != count:
            raise ValueError(f'{rater} 分配数量或唯一性错误')
        directory = root / 'assignments' / rater
        manifest = read_json(directory / 'manifest.json')
        rows = read_jsonl(directory / 'cases.jsonl')
        if manifest.get('assigned_annotator') != rater or manifest.get('package_id') != config['package_id'] or manifest.get('session_count') != count:
            raise ValueError(f'{rater} 项目元数据不匹配')
        if manifest.get('human_version') != simple.VERSION or manifest.get('rubric_versions') != {'review': simple.VERSION}:
            raise ValueError('标注口径版本不匹配')
        if [row['case_id'] for row in rows] != ids:
            raise ValueError('样本分配顺序/数量不匹配')
        for case in rows:
            sid = case['case_id']
            fingerprint = digest({key: value for key, value in case.items() if key != 'input_fingerprint'})
            if sid in all_cases or not fingerprint == case['input_fingerprint'] == config['case_fingerprints'].get(sid) == manifest['case_fingerprints'].get(sid):
                raise ValueError(f'重复或变更的样本：{sid}')
            all_cases[sid] = case
    if set(all_cases) != set(config['case_fingerprints']):
        raise ValueError('分发包未覆盖全部样本')
    return config, all_cases


def write_quality_report(source, destination, project, config):
    from collections import Counter
    from statistics import median
    cases = list(project.cases.values())
    lines = ['# 有效交互样本质量报告', '', f"批次 ID：`{config['package_id']}`", '',
             f"合格候选池：{project.manifest.get('eligible_pool_count', '未记录')} 条；seed=42 抽取 100 条，固定分配 30 / 30 / 40。", '',
             '| 维度 | 最少 | 中位数 | 最多 |', '| --- | ---: | ---: | ---: |']
    for key, label in [('effective_interactions','有效交互'),('user_rounds','原始用户消息'),('characters','可见正文字符'),('events','可见事件')]:
        values = [c.get('reading_stats', {}).get(key) for c in cases]
        values = [v for v in values if v is not None]
        if values:
            lines.append(f'| {label} | {min(values):,} | {median(values):,} | {max(values):,} |')
    languages = Counter(c.get('language_screen', {}).get('language', '未记录') for c in cases)
    lines += ['', '用户语言识别：' + '；'.join(f'{k}: {v}' for k,v in languages.items()) + '。表单版本 human_simple_v3；7 项基础选择，有新需求时共 9 项。']
    agents = Counter(c['agent'] for c in cases)
    excluded = Counter()
    for case in cases:
        excluded.update(case.get('interaction_quality', {}).get('excluded_prompt_counts', {}))
    lines += ['', f"覆盖 {len({c['repo_id'] for c in cases})} 个仓库。Agent 分布：" + '；'.join(f'{k}: {v}' for k,v in agents.items()) + '。', '',
              '这是经过可读性与多次实质交互筛选的子集，不能当作全量 SWE-Chat 的代表样本，也不宜直接用于跨 Agent 排名。仅筛选中文／英文用户交互。', '',
              '## 计数规则', '',
              '有效交互指一组实质性用户请求，随后有非空 assistant 回复或工具活动。连续发送且中间没有 Agent 活动的用户消息合并为一组。至少 8 次有效交互，其中至少 6 次有文字 assistant 回复；轮数无固定上限。', '',
              '排除固定 review 模板会话、明显重复拆段、起始环境/自动消息和源顺序有歧义的会话。对实质 prompt 序列去重。纯确认、自动通知、技能/命令展开模板及重复 prompt 不计有效次数，原文仍保留。短命令如 commit、git status 是用户实际操作请求，可以计数；不要求每次请求都新增项目需求。', '',
              '这些是可审计的启发式规则，不是人工意图标签。缺少响应不能推断 Agent 忽略要求，有工具活动也不证明要求已完成。判断需求是否新增、指令是否有问题仍由标注员完成。', '',
              '## 原文与追溯', '',
              '- 全部保留源 session 的 user / assistant / tool use / tool result 事件及原编号，不只截取前 8 轮。',
              '- 不保证项目从开始到结束的全部过程被源数据收录；thinking/system 不在界面，源工具结果可能已截断到 10KB。',
              '- `source_manifest.json`：规则版本、边界、来源文件、候选排除统计与样本指纹。',
              '- `candidate_audit.jsonl`：所有带 session 元数据的候选的首个排除原因，未做语义审查时的有效次数为 null。',
              '- `assignment_inventory.csv`：逐条分配、两种轮数、长度与事件数。',
              '- `assignments/*/cases.jsonl` 的 `interaction_quality`：每条 prompt 的分类原因、合并后的请求和响应 T 区间。',
              '- `trace_audit.json`：本次发布额外用原始 parquet 逐条比对的报告；重建包后可运行 `python scripts/audit_human_traces.py` 重新生成。', '',
              '## 已保留但不计有效请求的消息', '', '```json', json.dumps(excluded, ensure_ascii=False, indent=2), '```', '',
              '旧批次存在模板凑轮或旧表单问题，保存在 `annotation_archive/`。本次请使用 `annotation_release`；旧备份不导入新包，结果不能混收。', '']
    (destination / 'QUALITY_REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    if (source / 'candidate_audit.jsonl').exists():
        shutil.copy2(source / 'candidate_audit.jsonl', destination / 'candidate_audit.jsonl')


def build(source, destination, repo_root):
    if destination.exists() or destination.with_suffix('.zip').exists():
        raise ValueError('分发目录或压缩包已存在；请保留已发出的固定批次，另选新目录')
    project = HumanProject(source)
    if not project.simple or len(project.cases) != 100:
        raise ValueError('需要简洁版的 100 条冻结样本')
    from .human_interactions import analyze
    for case in project.cases.values():
        q = analyze([(e['turn'], 'user_prompt' if e['kind'] == 'continuation_context' else e['kind'], e['kind'] == 'continuation_context', e['text'], len(e['text']), bool(e['text'].strip())) for e in case['events']])
        if q['effective_interactions'] < 8 or q['answered_effective_interactions'] < 6 or q['template_session'] or q['fragment_count'] >= 2 or not q['first_prompt_substantive']:
            raise ValueError('需要至少 8 次有效用户交互，不能使用模板或纯确认凑轮数')
        if case.get('interaction_quality') is not None and case['interaction_quality'] != q:
            raise ValueError('有效交互审计与源事件不一致')
    ids = sorted(project.cases)
    random.Random(42).shuffle(ids)
    allocations = {RATERS[0]: ids[:30], RATERS[1]: ids[30:60], RATERS[2]: ids[60:]}
    config = dict(format=FORMAT, rubric_version=simple.VERSION, assignments=allocations,
                  case_fingerprints={sid: project.cases[sid]['input_fingerprint'] for sid in sorted(ids)},
                  allocation_method='Seed 42 shuffle of sorted frozen case IDs; disjoint 30/30/40; no outcome filtering.')
    config['package_id'] = package_identity(config)
    destination.mkdir(parents=True)
    write_json(destination / 'assignments.json', config)
    write_json(destination / 'source_manifest.json', project.manifest)
    for rater in RATERS:
        subset = [project.cases[sid] for sid in allocations[rater]]
        manifest = deepcopy(project.manifest)
        manifest.update(session_count=len(subset), sample_size_requested=len(subset), assigned_annotator=rater,
                        package_id=config['package_id'], parent_session_count=100,
                        case_fingerprints={case['case_id']: case['input_fingerprint'] for case in subset})
        directory = destination / 'assignments' / rater
        write_json(directory / 'manifest.json', manifest)
        write_jsonl(directory / 'cases.jsonl', subset)
    with (destination / 'assignment_inventory.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, lineterminator='\n', fieldnames=['annotator', 'position', 'case_id', 'user_rounds', 'effective_interactions', 'characters', 'events'])
        writer.writeheader()
        for rater in RATERS:
            for index, sid in enumerate(allocations[rater], 1):
                case = project.cases[sid]
                writer.writerow(dict(annotator=rater, position=index, case_id=sid, effective_interactions=case.get('interaction_quality', {}).get('effective_interactions'), **{key: case['reading_stats'][key] for key in ('user_rounds', 'characters', 'events')}))
    package_src = destination / 'src' / 'swe_chat_analysis'
    package_src.mkdir(parents=True)
    # Explicit allowlist: never copy .env, databases, raw parquet, or existing annotations.
    for name in ('__init__.py', 'human.py', 'human_simple.py', 'human_schema.py', 'human_team.py', 'human_offline.py', 'human_interactions.py', 'io.py', 'packet.py', 'study1.py', 'study2.py'):
        shutil.copy2(repo_root / 'src' / 'swe_chat_analysis' / name, package_src / name)
    shutil.copytree(repo_root / 'src' / 'swe_chat_analysis' / 'human_web', package_src / 'human_web')
    shutil.copy2(repo_root / 'scripts' / 'annotation_team.py', destination / 'annotate.py')
    shutil.copy2(repo_root / 'docs' / 'TEAM_ANNOTATION.md', destination / 'README.md')
    guide = (repo_root / 'Human_annotation.md').read_text(encoding='utf-8')
    guide = guide[guide.index('## 每条需要标多少内容'):].split('## 旧项目')[0]
    (destination / 'RUBRIC.md').write_text('# 标注口径与工作量\n\n' + guide.rstrip() + '\n', encoding='utf-8')
    shutil.copy2(repo_root / 'data' / 'swe-chat' / 'README.md', destination / 'DATA_SOURCE.md')
    (destination / '.gitignore').write_text('.local/\nsubmissions/\ncollected/\n*.sqlite3\n*.sqlite3-*\n__pycache__/\n*.pyc\n.venv/\n.env\n.DS_Store\n', encoding='utf-8')
    (destination / 'DATA_NOTICE.md').write_text('本包包含 SWE-Chat 原始数据的 100 条会话摘选（每条至少 8 次有效用户交互；原始消息另计），仅保留原始 user / assistant / tool use / tool result 事件及成本元数据，未裁剪正文；不含模型预标注。来源与数据集许可见 DATA_SOURCE.md（原始数据卡标记 odc-by）。样本及分配校验值见 assignments.json。\n', encoding='utf-8')
    write_quality_report(source, destination, project, config)
    load_bundle(destination)
    from .human_offline import generate
    generate(destination)
    archive = destination.with_suffix('.zip')
    if archive.exists():
        raise ValueError(f'压缩包已存在：{archive}')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(destination.rglob('*')):
            if path.is_file():
                z.write(path, Path(destination.name) / path.relative_to(destination))
    print(f'已打包：{destination}\nZIP：{archive}\n30 / 30 / 40，package_id={config["package_id"]}')


def local_project(root, rater):
    config, _ = load_bundle(root)
    directory = root / '.local' / rater
    source = root / 'assignments' / rater
    if not directory.exists():
        directory.mkdir(parents=True)
        for name in ('cases.jsonl', 'manifest.json'):
            shutil.copy2(source / name, directory / name)
    if read_json(directory / 'manifest.json') != read_json(source / 'manifest.json'):
        raise ValueError('本地任务与分发包不一致；不要把旧批次 .local 拷入新批次')
    project = HumanProject(directory)
    if project.manifest['package_id'] != config['package_id']:
        raise ValueError('本地批次不匹配')
    return project


def export(root, rater, destination=None, allow_partial=False):
    project = local_project(root, rater)
    result = project.export(rater)
    if not result['delivery']['complete'] and not allow_partial:
        d = result['delivery']
        raise ValueError(f'尚未完成：{d["completed_count"]}/{d["expected_count"]}；请提交所有样本。中途导出用 --allow-partial')
    destination = destination or root / 'submissions' / f'submission_{rater}.json'
    write_json(destination, result)
    print(f'已导出：{destination}（{result["delivery"]["completed_count"]}/{result["delivery"]["expected_count"]}）')
    return result


def analysis_csv(path, rows):
    fields = ['session_id', 'annotator', 'agent', 'initial_coverage', 'new_requirements', 'requirement_source', 'gap_driver', 'instruction_quality', 'literal_feasibility']
    metric_keys = ['late_requirement', 'first_late_requirement_turn', 'requirement_update_count', 'effective_interactions', 'user_rounds', 'visible_characters', 'observed_tool_events', 'user_rounds_after_first_update', 'tool_events_from_first_update', 'api_call_count', 'tool_call_count', 'total_tokens', 'duration_seconds']
    with path.open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fields + metric_keys)
        writer.writeheader()
        for row in rows:
            a = row['annotation']
            writer.writerow(dict(session_id=row['session_id'], annotator=row['annotator'], agent=row['agent'],
                                 initial_coverage=a['evolution']['initial_coverage'], new_requirements=a['evolution']['new_requirements'], requirement_source=a['evolution']['source'], gap_driver=a['gap']['driver'],
                                 instruction_quality=a['gap']['instruction_quality'], literal_feasibility=a['gap']['literal_feasibility'], **row['metrics']))


def merge(root, inputs, destination, allow_partial=False):
    config, cases = load_bundle(root)
    if destination.exists():
        raise ValueError('汇总目录已存在，请指定新目录以保留旧结果')
    rows, seen, raters = [], set(), set()
    for path in inputs:
        payload = read_json(path)
        delivery = payload.get('delivery', {})
        rater = delivery.get('assignment_id')
        if delivery.get('format') != 'swe_chat_delivery_v1' or delivery.get('package_id') != config['package_id']:
            raise ValueError(f'{path.name} 不属于当前批次或导出格式错误')
        if rater not in RATERS or rater in raters:
            raise ValueError('未知或重复标注员文件；同一人只提供一个最新导出')
        raters.add(rater)
        if payload.get('summary', {}).get('annotator') != rater or payload.get('summary', {}).get('human_version') != simple.VERSION:
            raise ValueError('导出身份或标注版本不匹配')
        if set(payload.get('annotations', {})) != {'review'}:
            raise ValueError('仅接受简洁版 review 标注')
        incoming = payload['annotations']['review']
        if not isinstance(incoming, list):
            raise ValueError('标注必须为数组')
        assigned = set(config['assignments'][rater])
        received = set()
        for row in incoming:
            sid = row.get('session_id')
            if sid not in assigned or sid in seen or row.get('annotator') != rater:
                raise ValueError(f'样本归属错误或重复：{sid}')
            case = cases[sid]
            if row.get('input_fingerprint') != case['input_fingerprint'] or row.get('rubric_version') != simple.VERSION or row.get('annotation_source') != 'human':
                raise ValueError(f'样本/版本校验失败：{sid}')
            if type(row.get('revision')) is not int or row['revision'] < 1:
                raise ValueError('非法提交版本')
            normalized = simple.validate(row['annotation'], case['events'])
            if simple.validate(row['raw_annotation'], case['events']) != normalized:
                raise ValueError(f'原始答案与提交答案不一致：{sid}')
            seen.add(sid); received.add(sid)
            rows.append(dict(session_id=sid, repo_id=case['repo_id'], agent=case['agent'], annotator=rater,
                             annotation_source='human', rubric_version=simple.VERSION,
                             input_fingerprint=case['input_fingerprint'], revision=row['revision'],
                             annotation=normalized, raw_annotation=row['raw_annotation'],
                             observed_costs=case['observed_costs'], turn_timestamps=case['turn_timestamps'],
                             metrics=simple.costs(case, normalized)))
        missing = sorted(assigned - received)
        if delivery.get('expected_count') != len(assigned) or delivery.get('completed_count') != len(incoming) or delivery.get('missing_case_ids') != missing or delivery.get('complete') is not (not missing):
            raise ValueError(f'{rater} 完成状态与实际条目不一致')
    missing = sorted(set(cases) - seen)
    if missing and not allow_partial:
        raise ValueError(f'未收齐：{len(seen)}/100，缺少 {len(missing)} 条；正式汇总需全部收齐，中期检查用 --allow-partial')
    order = {sid: index for index, sid in enumerate(sid for rater in RATERS for sid in config['assignments'][rater])}
    rows.sort(key=lambda row: order[row['session_id']])
    summary = dict(package_id=config['package_id'], rubric_version=simple.VERSION,
                   run_completeness=dict(expected=100, completed=len(rows), complete=not missing, missing_case_ids=missing,
                                         by_annotator={rater: {'expected': len(config['assignments'][rater]), 'completed': sum(row['annotator'] == rater for row in rows)} for rater in RATERS}),
                   **simple.summarize(rows),
                   agreement_note='30/30/40 为互不重叠分工，不能计算标注员间一致性；标注员差异可能影响组间比较。')
    destination.mkdir(parents=True)
    write_json(destination / 'merged.json', dict(summary=summary, annotations={'review': rows}))
    write_json(destination / 'summary.json', summary)
    write_jsonl(destination / 'annotations.jsonl', rows)
    analysis_csv(destination / 'analysis.csv', rows)
    print(f'已校验并汇总 {len(rows)}/100 条：{destination}')
    return summary


def main(root=None):
    parser = argparse.ArgumentParser(description='三人标注：固定分工、各自本地 serve、JSON 回收汇总（无需第三方依赖）')
    parser.add_argument('--bundle-dir', type=Path, default=root or Path('annotation_release'))
    sub = parser.add_subparsers(dest='command', required=True)
    build_parser = sub.add_parser('build')
    build_parser.add_argument('--source', type=Path, default=Path('outputs/human_zh_en_v3_100_seed42'))
    build_parser.add_argument('--destination', type=Path, default=Path('annotation_release'))
    serve_parser = sub.add_parser('serve')
    serve_parser.add_argument('--rater', choices=RATERS, required=True)
    serve_parser.add_argument('--port', type=int, default=8765)
    export_parser = sub.add_parser('export')
    export_parser.add_argument('--rater', choices=RATERS, required=True)
    export_parser.add_argument('--output', type=Path)
    export_parser.add_argument('--allow-partial', action='store_true')
    status_parser = sub.add_parser('status')
    status_parser.add_argument('--rater', choices=RATERS, required=True)
    merge_parser = sub.add_parser('merge')
    merge_parser.add_argument('inputs', type=Path, nargs='+')
    merge_parser.add_argument('--output-dir', type=Path, default=Path('collected'))
    merge_parser.add_argument('--allow-partial', action='store_true')
    sub.add_parser('verify')
    sub.add_parser('offline', help='生成可双击打开的离线 HTML')
    args = parser.parse_args()
    try:
        if args.command == 'build':
            build(args.source, args.destination, Path(__file__).resolve().parents[2])
        elif args.command == 'offline':
            from .human_offline import generate
            generate(args.bundle_dir)
        elif args.command == 'verify':
            config, cases = load_bundle(args.bundle_dir)
            print(f'校验通过：{len(cases)} 条，30/30/40，批次 {config["package_id"]}')
        elif args.command == 'export':
            export(args.bundle_dir, args.rater, args.output, args.allow_partial)
        elif args.command == 'merge':
            merge(args.bundle_dir, args.inputs, args.output_dir, args.allow_partial)
        else:
            project = local_project(args.bundle_dir, args.rater)
            if args.command == 'status':
                result = project.export(args.rater)
                print(json.dumps(result['delivery'], ensure_ascii=False, indent=2))
                return
            token = secrets.token_urlsafe(32)
            with ThreadingHTTPServer(('127.0.0.1', args.port), handler(project, token)) as server:
                print(f'{args.rater}：{len(project.cases)} 条；进度保存在 {project.database}\n打开 http://127.0.0.1:{server.server_port}/#token={token}', flush=True)
                print('Ctrl+C 停止；下次运行同一命令可恢复。', flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
