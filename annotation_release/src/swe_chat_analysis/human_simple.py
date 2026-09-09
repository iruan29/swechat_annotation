"""Compact, retrospective human rubric. No model labels or counterfactual cost estimates."""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean, median
from copy import deepcopy

VERSION = 'human_simple_v3'
STAGE = 'review'
RUBRIC = '''以整个会话的主要项目目标为单位，先通读用户消息，再逐轮查看 Agent 证据。
最终要求是可确认的验收要求，不等于 Agent 实际实现的功能。
“有新需求”：初始指令之后，用户首次增加或明确功能、约束或验收标准；包括初始遗漏后补充的要求。重复催促、重新解释同一要求、修复未实现的既有要求不算。
需求来源：用户偏好=风格、体验、个人选择；项目需求=功能正确性、兼容性、接口、环境或验收约束；存在两类实质新需求选“两者都有”。没证据则无法判断。
缺口原因只选最有直接证据的主要原因：信息/认知局限包括不可观察的信息、知识不足或错误理解；偏好/表达未说明包括个人偏好与沟通方式。不能从姓名、语言或身份猜文化和能力；无法区分主因选无法判断。
完整且无已知错误时，原因选不适用；有缺口但原因没证据时选无法判断。
Literal=执行明确指令；仅澄清=询问歧义但未识别隐藏目标或现实约束；主动发现并行动=在用户指出前识别缺口并改变行动。
行为可多选，但只选会话中明确发生的行为；“无法判断”不与其他选项并选。提前完成需要完成证据，仅承诺不算；忽略证据需要明确反例，不能由日志缺口推断。
不需要填写项目概况、文字理由或逐事件长表。有新需求时选择首次出现的用户消息，系统自动计算后续成本；不能估计反事实节省。
这些说明用于统一分类边界，不保证未经重复标注测量的一致性。'''


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
    evolution=obj('一、需求覆盖与新增',
        initial_coverage=choice('初始 instruction 覆盖了多少最终要求', '没有|一部分|全部|无法判断'),
        new_requirements=choice('用户在交互中有没有提出新需求', '有|没有|无法判断'),
        source=dict(choice('新需求来源', '用户偏好|项目需求|两者都有|无法判断'), nullable=True),
        first_new_turn=dict(type='integer', label='首次提出新需求的用户消息（用于自动计算成本）', nullable=True),
        behaviors=array('Agent 行为（可多选）', choice('行为', BEHAVIORS))),
    gap=obj('二、初始指令的缺口',
        instruction_quality=choice('初始 instruction 是否有问题', '完整且无已知错误|不完整|错误或误导|不完整且错误或误导|无法判断'),
        driver=choice('有证据支持的主要原因（单选）', '信息或认知局限|偏好或表达未说明|无法判断|不适用'),
        literal_feasibility=choice('仅完成初始字面要求，能否达成最终项目目标', '能|只能部分达成|不能|无法判断'),
        response=choice('Agent 对指令缺口的主要处理方式', 'Literal 执行|仅澄清原指令歧义|主动发现缺口并行动|发现缺口但未行动|用户指出后才调整|无需处理缺口|无法判断')))


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
    e, g = raw['evolution'], raw['gap']
    values = e['behaviors']
    if not values or len(values) != len(set(values)) or len(values) > 1 and '无法判断' in values:
        raise ValueError('请选择 Agent 行为；无法判断不能与其他行为并选')
    users = [event['turn'] for event in events if event['kind'] == 'user_prompt']
    if e['new_requirements'] == '有':
        if e['source'] is None:
            raise ValueError('有新需求时请选择需求来源')
        if e['first_new_turn'] not in users or e['first_new_turn'] <= min(users):
            raise ValueError('请选择初始指令之后的用户消息；该 T 编号不在本会话的后续用户消息中')
    elif e['source'] is not None or e['first_new_turn'] is not None:
        raise ValueError('没有或无法判断新需求时，来源和首次消息必须留空')
    if g['instruction_quality'] == '完整且无已知错误' and g['driver'] != '不适用':
        raise ValueError('初始指令无已知问题时，原因应选不适用')
    if g['instruction_quality'] != '完整且无已知错误' and g['driver'] == '不适用':
        raise ValueError('有问题或无法判断时，原因应选有证据的主因或无法判断')
    return deepcopy(raw)


def costs(case, annotation):
    events = case['events']
    first = annotation['evolution']['first_new_turn']
    late = {'有': True, '没有': False, '无法判断': None}[annotation['evolution']['new_requirements']]
    return {
        'late_requirement': late,
        'first_late_requirement_turn': first,
        'requirement_update_count': None,
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
            'interpretation': '仅已提交会话的描述性关联；后出现=用户在初始之后首次明确的重要新增/补充；重复催促和旧要求修复排除。不再逐事件计数，需求数量为 null。缺失成本不填零。样本限于可人工阅读的会话，不代表全数据。无法观测清晰初始指令的反事实成本，不提供节省量或因果结论。'}
