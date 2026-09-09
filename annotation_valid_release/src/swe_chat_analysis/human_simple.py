"""Compact, retrospective human rubric. No model labels or counterfactual cost estimates."""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from copy import deepcopy

VERSION = 'human_simple_v2'
STAGE = 'review'
RUBRIC = '''以整个会话的主要项目目标为单位，先通读用户消息，再逐轮展开 agent / 工具证据。
最终要求指会话中可确认的最终验收要求，不等于 agent 最终实际实现的功能。无法确认选“无法判断”。
初始不完整：一开始就存在的重要要求未表达；真实新增：用户后来才改变目标，不倒推为初始错误。
需求来源与触发方式分开：偏好/项目约束是来源；主动询问/新证据/用户自行提出是触发方式。
只在有明确证据时判断用户局限；不能从姓名、语言或身份猜测文化、专业能力。
Literal：执行明确指令。澄清：消解原指令歧义但没有发现目标与实际情况的差距。
主动发现缺口并行动：有证据说明 agent 识别潜在目标、指令和项目现实的差距，并据此改变行动。
行为可多选，但须有证据编号；“提前发现并完成”需要用户明确提出前的发现和完成证据。
“正确更新”需要实现/验证证据；仅承诺不算完成。修复已有要求不计作新增要求。
成本由系统统计，不能标注或估算“如果一开始说清楚会少花多少”；组间差异只是描述性关联。
所有判断都是全会话回顾性判断，不是遮蔽未来信息的实验。'''


def choice(label, values):
    return dict(type='string', label=label, enum=values.split('|'))


def text(label):
    return dict(type='string', label=label)


def array(label, item):
    return dict(type='array', label=label, items=item)


def obj(label, **fields):
    return dict(type='object', label=label, properties=fields)


BEHAVIORS = '按明确要求执行|提前发现并完成要求|主动询问后发现要求|收到新证据后正确更新|只修补表面症状|忽略新证据|满足新要求但破坏已有要求|无法判断'
SPEC = obj('',
    overview=obj('项目概况',
        project=text('主要项目目标与最终验收要求（简述）'),
        assessability=choice('会话是否足以判断', '充分|部分可判断|无法判断')),
    evolution=obj('一、需求覆盖与演化',
        initial_coverage=choice('初始 instruction 覆盖了多少最终要求', '没有|一部分|全部|无法判断'),
        update_extent=choice('用户要求随交互更新的程度', '无更新|少量补充或调整|实质变化|无法判断'),
        behaviors=array('Agent 行为（可多选）', choice('行为', BEHAVIORS)),
        evidence_turns=array('判断依据 T 编号', dict(type='integer', label='T 编号')),
        rationale=text('判断理由（说明覆盖与行为证据）')),
    updates=array('需求事件（有新增、变化或旧要求修复时添加）', obj('需求事件',
        requirement=text('具体要求 / 变化内容'),
        turn=dict(type='integer', label='首次明确该事件的 T 编号'),
        change=choice('变化类型', '初始遗漏的既有要求|用户真正新增或改变目标|既有要求的实现修复|无法判断'),
        source=choice('要求来源', '用户偏好|项目客观要求|两者都有|无法判断'),
        trigger=choice('如何发现 / 提出', '用户自行提出|Agent 主动询问|Agent 主动检查发现|工具或运行结果等新证据|无法判断'),
        response=choice('Agent 对该事件的响应', BEHAVIORS),
        evidence_turns=array('响应证据 T 编号', dict(type='integer', label='T 编号')),
        rationale=text('证据说明（提前发现需给出时序；回归需说明破坏了什么）'))),
    gap=obj('二、初始指令的缺口',
        instruction_quality=choice('初始 instruction 是否有问题', '完整且无已知错误|不完整|错误或误导|不完整且错误或误导|无法判断'),
        drivers=array('有证据支持的原因（可多选）', choice('原因', '可观察信息有限|偏好未表达|文化或沟通习惯|专业知识局限|错误心智模型|其他有证据原因|无法判断|不适用')),
        literal_feasibility=choice('有能力地仅完成初始字面要求，能否达成最终项目目标', '能|只能部分达成|不能|无法判断'),
        response=choice('Agent 对指令缺口的主要处理方式', 'Literal 执行|仅 sensemaking 澄清|主动发现用户目标与现实缺口并行动|发现缺口但未据此行动|用户指出后才调整|无需处理缺口|无法判断'),
        evidence_turns=array('判断依据 T 编号', dict(type='integer', label='T 编号')),
        rationale=text('指令问题、用户原因与 Agent 行动的证据；未知请说明原因')),
    notes=text('补充说明（可留空；多任务、日志缺失等）'))


def schema():
    spec = deepcopy(SPEC)
    def fields(node, name=''):
        node['field'] = name
        for key, child in node.get('properties', {}).items():
            fields(child, key)
        if 'items' in node:
            fields(node['items'], name)
    fields(spec)
    return spec


def validate(raw, events):
    from .human_schema import check_answers
    check_answers(schema(), raw)
    turns = {event['turn'] for event in events}
    initial = min(event['turn'] for event in events if event['kind'] == 'user_prompt')
    def walk(value, key=''):
        if isinstance(value, dict):
            for name, child in value.items():
                walk(child, name)
        elif isinstance(value, list):
            if key == 'evidence_turns' and not value:
                raise ValueError('请为每个判断填写至少一个证据 T 编号')
            for child in value:
                walk(child, 'turn' if key == 'evidence_turns' else key)
        elif key == 'turn' and value not in turns:
            raise ValueError(f'T{value} 不在本会话中')
        elif key in {'project', 'requirement', 'rationale'} and not value.strip():
            raise ValueError('请填写项目、具体要求和判断理由；无法判断也请说明原因')
    walk(raw)
    if not raw['evolution']['behaviors'] or not raw['gap']['drivers']:
        raise ValueError('请选择 Agent 行为和指令问题原因；可选择无法判断 / 不适用')
    for values in (raw['evolution']['behaviors'], raw['gap']['drivers']):
        if len(values) != len(set(values)) or len(values) > 1 and set(values) & {'无法判断', '不适用'}:
            raise ValueError('选项不能重复；无法判断 / 不适用不能与其他选项并选')
    updates = raw['updates']
    if any(event['turn'] <= initial for event in updates):
        raise ValueError('需求事件应在初始用户指令之后')
    real_updates = [event for event in updates if event['change'] != '既有要求的实现修复']
    extent = raw['evolution']['update_extent']
    if extent == '无更新' and real_updates or extent in {'少量补充或调整', '实质变化'} and not real_updates:
        raise ValueError('更新程度与需求事件不一致；真实更新须至少记录一项')
    return deepcopy(raw)


def costs(case, annotation):
    events = case['events']
    updates = [item for item in annotation['updates'] if item['change'] in {'初始遗漏的既有要求', '用户真正新增或改变目标'}]
    first = min((item['turn'] for item in updates), default=None)
    unknown = annotation['evolution']['update_extent'] == '无法判断' or any(item['change'] == '无法判断' for item in annotation['updates'])
    return {
        'late_requirement': True if first is not None else None if unknown else False,
        'first_late_requirement_turn': first,
        'requirement_update_count': len(updates),
        'user_rounds': len(case['user_turns']),
        'effective_interactions': case.get('interaction_quality', {}).get('effective_interactions'),
        'visible_characters': sum(len(event['text']) for event in events),
        'observed_tool_events': sum(event['kind'] == 'tool_use' for event in events),
        'user_rounds_after_first_update': sum(event['kind'] == 'user_prompt' and event['turn'] > first for event in events) if first is not None else None,
        'tool_events_from_first_update': sum(event['kind'] == 'tool_use' and event['turn'] >= first for event in events) if first is not None else None,
        **{key: case['observed_costs'].get(key) for key in ('api_call_count', 'tool_call_count', 'total_tokens', 'duration_seconds')},
    }


def summarize(rows):
    metrics = ('effective_interactions', 'user_rounds', 'observed_tool_events', 'api_call_count', 'tool_call_count', 'total_tokens', 'duration_seconds')
    def stats(group):
        result = {'sessions': len(group)}
        for key in metrics:
            values = [row['metrics'][key] for row in group if isinstance(row['metrics'][key], (int, float))]
            result[key] = {'n': len(values), 'mean': mean(values) if values else None, 'median': median(values) if values else None}
        return result
    groups = {name: stats([row for row in rows if row['metrics']['late_requirement'] is flag]) for name, flag in [('有晚出现需求', True), ('无晚出现需求', False), ('无法判断', None)]}
    strata = defaultdict(list)
    for row in rows:
        strata[(row['agent'], row['annotation']['evolution']['initial_coverage'])].append(row)
    return {'cost_comparison': groups,
            'cost_by_instruction_quality': {quality: stats([row for row in rows if row['annotation']['gap']['instruction_quality'] == quality]) for quality in sorted({row['annotation']['gap']['instruction_quality'] for row in rows})},
            'by_agent_and_initial_coverage': [{'agent': agent, 'initial_coverage': coverage, 'groups': {name: stats([row for row in group if row['metrics']['late_requirement'] is flag]) for name, flag in [('有晚出现需求', True), ('无晚出现需求', False)]}} for (agent, coverage), group in strata.items()],
            'instruction_quality': dict(Counter(row['annotation']['gap']['instruction_quality'] for row in rows)),
            'interpretation': '仅已提交会话的描述性关联；后出现=初始之后首次明确的重要新增/变更，旧要求修复排除。缺失成本不填零。样本限于可人工阅读的会话，不代表全数据。无法观测清晰初始指令的反事实成本，不提供节省量或因果结论。'}
