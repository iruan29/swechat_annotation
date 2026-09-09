"""Length-bounded, reproducible sampling from raw conversations."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import time

import pyarrow.parquet as pq

from .io import SESSION_COLUMNS, _available_columns, read_conversations, write_jsonl
from .human_simple import VERSION, STAGE

KINDS = {'user_prompt', 'assistant_response', 'tool_use', 'tool_result'}


def scan(path):
    stats = defaultdict(lambda: Counter())
    columns = _available_columns(path, ['session_id', 'turn_type', 'is_continuation', 'content', 'tool_name', 'file_path', 'command'])
    for batch in pq.ParquetFile(path).iter_batches(batch_size=4096, columns=columns):
        for row in batch.to_pylist():
            if row['turn_type'] not in KINDS:
                continue
            item = stats[str(row['session_id'])]
            item['events'] += 1
            text = str(row.get('content') or '')
            if row['turn_type'] in {'tool_use', 'tool_result'}:
                text = '\n'.join(f'{key}: {row[key]}' for key in ('tool_name', 'file_path', 'command') if row.get(key)) + '\n' + text
            item['characters'] += len(text)
            if row['turn_type'] == 'user_prompt' and not row.get('is_continuation'):
                item['user_rounds'] += 1
                item['user_characters'] += len(text)
            elif row['turn_type'] == 'assistant_response':
                item['assistant_responses'] += bool(text.strip())
    return stats


def compact_scan(path):
    rows = defaultdict(list)
    columns = _available_columns(path, ['session_id', 'turn_number', 'turn_type', 'is_continuation', 'content', 'tool_name', 'file_path', 'command'])
    for batch in pq.ParquetFile(path).iter_batches(batch_size=4096, columns=columns):
        for row in batch.to_pylist():
            kind = row['turn_type']
            if kind not in KINDS:
                continue
            content = str(row.get('content') or '')
            if kind in {'tool_use', 'tool_result'}:
                content = '\n'.join(f'{k}: {row[k]}' for k in ('tool_name', 'file_path', 'command') if row.get(k)) + '\n' + content
            rows[str(row['session_id'])].append((int(row.get('turn_number') or 0), kind, bool(row.get('is_continuation')), content if kind == 'user_prompt' else '', len(content), bool(content.strip())))
    return rows


def prepare(args):
    from .human import make_case, digest
    from .human_interactions import analyze, normalize, VERSION as FILTER_VERSION
    data, output = Path(args.data_dir), Path(args.output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError('输出目录必须为空；不能覆盖已冻结批次')
    if not (args.min_prompts > 0 and (args.max_prompts == 0 or args.max_prompts >= args.min_prompts)
            and 0 <= args.min_chars <= args.max_chars and args.max_events > 0 and args.sample_size > 0):
        raise ValueError('筛选边界无效')
    print('扫描完整源表，按实质性用户请求与后续 Agent 活动计算有效交互…', flush=True)
    records = compact_scan(data / 'conversations.parquet')
    sessions = {str(r['session_id']): r for r in pq.read_table(data / 'sessions.parquet', columns=_available_columns(data / 'sessions.parquet', SESSION_COLUMNS)).to_pylist()}
    eligible, audits, fingerprints, languages = {}, [], set(), {}
    for sid in sorted(sessions):
        ev = records.get(sid, [])
        chars = sum(e[4] for e in ev)
        raw_count = sum(e[1] == 'user_prompt' and not e[2] for e in ev)
        reason = None
        q = None
        if raw_count < args.min_prompts:
            reason = 'too_few_raw_messages'
        elif not args.min_chars <= chars <= args.max_chars or len(ev) > args.max_events:
            reason = 'readability_bounds'
        else:
            q = analyze(ev)
            if q['template_session']: reason = 'review_template'
            elif q['duplicate_turns']: reason = 'ambiguous_source_order'
            elif q['fragment_count'] >= 2: reason = 'repeated_substring_fragments'
            elif not q['first_prompt_substantive']: reason = 'initial_prompt_automatic_or_context_only'
            elif q['effective_interactions'] < args.min_prompts: reason = 'too_few_effective_interactions'
            elif args.max_prompts and q['effective_interactions'] > args.max_prompts: reason = 'too_many_effective_interactions'
            elif q['answered_effective_interactions'] < min(6, args.min_prompts): reason = 'too_few_textual_responses'
            else:
                turns = {p['turn'] for p in q['prompts'] if p['reason'] is None}
                key = digest([normalize(e[3]) for e in sorted(ev, key=lambda e:e[0]) if e[1] == 'user_prompt' and e[0] in turns])
                if key in fingerprints: reason = 'duplicate_user_sequence'
                else: fingerprints.add(key)
        if reason is None and getattr(args, 'language_filter', False):
            from .human_language import screen
            languages[sid] = screen(ev, q)
            if not languages[sid]['accepted']: reason = 'language_not_chinese_or_english'
        audits.append(dict(case_id=sid, exclusion_reason=reason, raw_user_messages=raw_count,
                           effective_interactions=q['effective_interactions'] if q else None, characters=chars, events=len(ev)))
        if reason is None:
            eligible[sid] = q
    if len(eligible) < args.sample_size:
        raise ValueError(f'只有 {len(eligible)} 条合格候选，少于 {args.sample_size}；请显式放宽可读长度，勿降低真实性要求')
    print(f'基础合格候选 {len(eligible)} 条；读取候选的完整所选类型记录，检查标注证据…', flush=True)
    source = read_conversations(data / 'conversations.parquet', sorted(eligible))
    prepared, relevance = {}, {}
    review_path = Path(__file__).resolve().parents[2] / 'docs' / 'human_selection_review.json'
    review = json.loads(review_path.read_text()) if getattr(args,'relevance_filter',False) and review_path.exists() else {}
    exclusions = {r['case_id']:r for r in review.get('exclusions',[])}
    for sid in sorted(eligible):
        case = make_case(sessions[sid], source.pop(sid), {}, args.seed)
        case['interaction_quality'] = eligible[sid]
        if sid in languages: case['language_screen'] = languages[sid]
        case['reading_stats'] = dict(user_rounds=len(case['user_turns']), effective_interactions=eligible[sid]['effective_interactions'],
                                    characters=sum(len(e['text']) for e in case['events']), events=len(case['events']))
        if getattr(args, 'relevance_filter', False):
            from .human_relevance import assess
            relevance[sid] = assess(case)
            excluded = exclusions.get(sid)
            if excluded and excluded['trace_fingerprint'] == digest(case['events']):
                relevance[sid].update(eligible=False,reason=excluded['reason'],review_exclusion=True)
            if not relevance[sid]['eligible']:
                next(a for a in audits if a['case_id']==sid)['exclusion_reason'] = 'insufficient_visible_annotation_evidence'
                continue
        case['input_fingerprint'] = digest({k:v for k,v in case.items() if k != 'input_fingerprint'})
        prepared[sid] = case
    if len(prepared) < args.sample_size:
        raise ValueError(f'仅 {len(prepared)} 条有足够标注证据，不能凑满 {args.sample_size}；请扩大候选池')
    selected = random.Random(args.seed).sample(sorted(prepared), args.sample_size)
    cases = [prepared[sid] for sid in selected]
    print(f'可标注候选 {len(prepared)} 条；冻结 {len(cases)} 条。', flush=True)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / 'cases.jsonl', cases)
    write_jsonl(output / 'candidate_audit.jsonl', audits)
    if review:
        (output / 'selection_review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
    if relevance:
        write_jsonl(output / 'selection_audit.jsonl', [dict(case_id=sid, **relevance[sid]) for sid in selected])
    manifest = dict(human_version=VERSION, rubric_versions={STAGE:VERSION}, seed=args.seed,
        sample_size_requested=args.sample_size, session_count=len(cases), eligible_pool_count=len(prepared), base_pool_count=len(eligible),
        selection_review_digest=digest(review) if review else None,
        relevance_filter="annotation_evidence_v2: at least two later substantive user messages with textual agent responses and diverse request/constraint/clarification cues" if relevance else None,
        language_filter='Chinese and English only' if getattr(args, 'language_filter', False) else 'not applied',
        filter_version=FILTER_VERSION, bounds={k:getattr(args,k) for k in ('min_prompts','max_prompts','min_chars','max_chars','max_events')},
        sampling='Uniform seed-based sample without replacement after effective interaction and readability filtering; exact normalized substantive user sequences deduplicated; observable dialogue evidence enrichment when enabled; cue matches are not annotation answers and this is not a prevalence sample.',
        interaction_definition='Distinct substantive user request group followed by visible assistant/tool activity. Consecutive users without agent activity share one exchange. Acknowledgements, repeated prompts, automatic notifications, skill/command scaffolding and continuation records do not qualify. Activity is not proof of success.',
        exclusions=dict(Counter(a['exclusion_reason'] for a in audits if a['exclusion_reason'])),
        case_fingerprints={c['case_id']:c['input_fingerprint'] for c in cases},
        created_at_unix=int(time.time()), commits_included=False,
        source_files={n:{'bytes':(data/n).stat().st_size,'mtime_ns':(data/n).stat().st_mtime_ns} for n in ('sessions.parquet','conversations.parquet')})
    (output / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    import csv
    with (output / 'sample_inventory.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['case_id','user_rounds','effective_interactions','characters','events'])
        writer.writeheader()
        writer.writerows(dict(case_id=c['case_id'],**c['reading_stats']) for c in cases)
    print(f'已冻结 {len(cases)} 条：{output}',flush=True)
