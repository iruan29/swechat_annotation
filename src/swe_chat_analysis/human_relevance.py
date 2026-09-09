"""Evidence availability for targeted annotation sampling, not annotation answers."""
import re
from .human_interactions import prompt_reason

VERSION = 'annotation_evidence_v2'
USER_CUES = {
    'intent_correction': r"^(?:no|wait|but|not|hmm)\b|\b(?:i meant|i mean|i was talking|not what i|misunderstood|actually want|instead of|rather than|shouldn't|should not|why did you|but i (?:want|need|don't|do not))\b|我的意思|我说的是|不是.{0,25}(?:而是|是要)|不应该|理解错|不是我想|不对|我希望的是|还是不|仍然|但是",
    'limited_understanding': r"\b(?:i thought|i assumed|i don'?t understand|i am confused|i'm confused|my mistake|i forgot|i didn'?t (?:know|realize)|i was wrong)\b|我以为|我不理解|我理解|忘了|没想到|我搞错|才知道",
    'preference_or_requirement': r"\b(?:should|must|need|want|prefer|also|instead|rather|could we|can we|can you)\b|\b(?:i (?:want|prefer|would like)|i'd (?:like|rather)|we (?:need|should)|it (?:should|must)|also (?:add|need|want)|make (?:it|the) (?:more|less)|can we (?:add|change|keep|remove))\b|我希望|我想|想要|需要增加|还需要|能不能|不要|改成|希望|必须",
    'project_constraint': r"\b(?:backward.compatib|incompatib\w*|doesn'?t (?:work|support|match)|not (?:working|supported)|fails? (?:when|because)|error|expected|permission|constraint|requirement|schema|api)\b|兼容|报错|错误|实际|不一致|不支持|权限|约束|接口|无法",
}
CLARIFY = re.compile(r"\b(?:do you mean|could you clarify|would you prefer|which (?:option|approach)|can you confirm|what (?:exactly|do you want)|before (?:i|we).{0,35}clarif)\b|你希望|你的意思|请确认|需要确认|想确认|请问", re.I)
DISCOVER = re.compile(r"\b(?:root cause|turns out|the (?:issue|problem) is|incompatible|not possible|actually|constraint)\b|根因|原因是|实际|不支持|不兼容", re.I)
PROCESS = re.compile(r'^(?:(?:please|yes|ok|okay)\W+)?(?:commit|push|merge|create (?:a )?pr|git status|run (?:the )?tests)[\w\W]{0,12}$',re.I)


def assess(case):
    events = case['events']
    by_turn = {e['turn']:e for e in events}
    users = [e for e in events if e['kind'] == 'user_prompt' and prompt_reason(e['text']) is None]
    if not users:
        return dict(version=VERSION, eligible=False, evidence=[], reason='no_substantive_user')
    initial = users[0]
    evidence = []
    for block in case['interaction_quality']['exchanges']:
        for turn in block['substantive_turns']:
            e = by_turn[turn]
            if turn == initial['turn'] or len(e['text'].strip()) < 12 or PROCESS.fullmatch(e['text'].strip()):
                continue
            replies = [by_turn[t] for t in block['assistant_turns'] if t > turn and len(by_turn[t]['text'].strip()) >= 60 and not re.match(r'^(?:API Error:|Error: (?:rate limit|authentication)|Rate limit exceeded)',by_turn[t]['text'].strip(),re.I)]
            if not replies:
                continue
            cues = [name for name, pattern in USER_CUES.items() if re.search(pattern,e['text'],re.I)]
            before = [a for a in events if a['kind']=='assistant_response' and a['turn']<turn]
            preceding = before[-1] if before else None
            if preceding and CLARIFY.search(preceding['text']): cues.append('agent_clarification')
            response = max(replies,key=lambda a:len(a['text']))
            if cues and DISCOVER.search(response['text']): cues.append('agent_explanation_of_constraint')
            if not cues:
                continue
            evidence.append(dict(user_turn=turn, assistant_turn=response['turn'], cues=cues,
                user_excerpt=e['text'][:900], assistant_excerpt=response['text'][:1100],
                preceding_assistant_turn=preceding['turn'] if preceding and 'agent_clarification' in cues else None))
    # Demand more than an isolated keyword: two later substantive user messages,
    # both with textual agent response, and at least two different evidence cues.
    kinds = {kind for e in evidence for kind in e['cues']}
    eligible = len(evidence)>=2 and len(kinds)>=2 and bool(kinds & {'intent_correction','limited_understanding','preference_or_requirement','agent_clarification'})
    return dict(version=VERSION, eligible=eligible, initial_turn=initial['turn'],initial_excerpt=initial['text'][:1100],
                evidence=evidence, cue_types=sorted(kinds),
                reason='multiple_interpretable_request_response_segments' if eligible else 'insufficient_visible_annotation_evidence')
