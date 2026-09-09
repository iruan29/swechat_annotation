"""Auditable heuristics for substantive user exchanges; never rewrite source text."""
import re
from collections import Counter

VERSION = 'effective_interactions_v1'
REVIEW = 'you are a code reviewer. your job is to review code changes and provide actionable feedback.'
MACHINE = re.compile(r'^(?:\[Request interrupted|\[Image:|<task-notification\b|<local-command|<command-(?:message|name)>|<bash-(?:input|stdout|stderr)>|<system-reminder>|<objective>|<execution_context>|<teammate-message\b|Base directory for this skill:|This session is being continued|Continue from where you left off\.|IT IS CRITICAL THAT YOU FOLLOW THIS COMMAND:)', re.I)
ACK = re.compile(r"^(?:yes|y|no|n|ok(?:ay)?|sure|good|great|thanks?|thank you|continue|go ahead|proceed|yep|yeah|yess|good idea|si grazie|よいです|はい|ありがとう|네|감사합니다|merged|checked|done|clear|ran it|lgtm|yes please|please continue|let'?s do it|继续|好的?|是的?|可以|没问题|嗯|对)[.!。！,，\s]*$", re.I)


def normalize(text):
    text = re.sub(r'\[Image[^\]]*\]', '', text, flags=re.I)
    return re.sub(r'\s+', ' ', text).strip().casefold()


def prompt_reason(text):
    text = ''.join(c for c in text if c.isprintable() or c in '\n\t').strip()
    if not text:
        return 'empty'
    if REVIEW in text.casefold():
        return 'review_template'
    # Mixed environment wrappers are common; retain any actual request following them.
    text = re.sub(r'<system_instruction>.*?</system_instruction>', '', text, flags=re.S).strip()
    if (not text or MACHINE.match(text) or re.match(r'^(?:Tool loaded\.|Unknown skill:|Stop hook feedback:|◇ ultraplan|The remote ultraplan session|Ultraplan approved in browser|## Context\s+- Current git status:|# Commit Rationale Annotation|# Smart Commit with Gitmoji|# ドキュメントレビュー)', text)):
        return 'automatic_or_context'
    text = re.sub(r'<ide_(?:selection|opened_file)>.*?</ide_(?:selection|opened_file)>', '', text, flags=re.S).strip()
    if not text:
        return 'automatic_or_context'
    if ACK.fullmatch(text):
        return 'acknowledgement_only'
    if len(re.sub(r'[^\w]', '', text)) < 4:
        return 'short_or_menu_choice'
    if text.startswith('/') and not re.search(r'\s+\S', text):
        return 'command_only'
    return None


def analyze(events):
    """Compact rows: turn, kind, continuation, user text, visible length, nonempty.

    Adjacent user messages without agent activity share one exchange. Machine
    records do not establish user boundaries. Distinct substantive requests plus
    subsequent visible agent/tool activity establish effective exchanges.
    """
    rows = sorted(events, key=lambda e: e[0])
    raw = [e for e in rows if e[1] == 'user_prompt' and not e[2]]
    seen = set()
    prompts = []
    blocks = []
    pending = None
    for turn, kind, continuation, text, length, nonempty in rows:
        if kind == 'user_prompt' and not continuation:
            reason = prompt_reason(text)
            norm = normalize(text)
            if reason is None and norm in seen:
                reason = 'duplicate_prompt'
            seen.add(norm)
            prompts.append(dict(turn=turn, reason=reason))
            # Synthetic source records should not split real user exchanges.
            if reason in {'automatic_or_context', 'empty', 'review_template'}:
                continue
            if pending is None or pending['activity_turns']:
                if pending is not None:
                    blocks.append(pending)
                pending = dict(user_turns=[], substantive_turns=[], activity_turns=[], assistant_turns=[])
            pending['user_turns'].append(turn)
            if reason is None:
                pending['substantive_turns'].append(turn)
        elif kind in {'assistant_response', 'tool_use', 'tool_result'} and nonempty and pending is not None:
            pending['activity_turns'].append(turn)
            if kind == 'assistant_response':
                pending['assistant_turns'].append(turn)
    if pending is not None:
        blocks.append(pending)
    effective = [b for b in blocks if b['substantive_turns'] and b['activity_turns']]
    norms = [normalize(e[3]) for e in raw]
    fragments = sum(len(t) >= 80 and any(t != earlier and t in earlier for earlier in norms[:i]) for i, t in enumerate(norms))
    return dict(version=VERSION, raw_user_messages=len(raw), effective_interactions=len(effective),
                answered_effective_interactions=sum(bool(b['assistant_turns']) for b in effective),
                substantive_user_messages=sum(p['reason'] is None for p in prompts),
                excluded_prompt_counts=dict(Counter(p['reason'] for p in prompts if p['reason'])),
                template_session=any(p['reason'] == 'review_template' for p in prompts),
                fragment_count=fragments, first_prompt_substantive=bool(prompts and prompts[0]['reason'] is None and not raw[0][3].lstrip().startswith('<system_instruction>')),
                duplicate_turns=len({e[0] for e in rows}) != len(rows),
                prompts=prompts, exchanges=blocks)
