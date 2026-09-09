#!/usr/bin/env python3
"""Audit frozen user-message segments against the source event table, without relabeling answers."""
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from swe_chat_analysis.human import make_case
from swe_chat_analysis.human_team import load_bundle
from swe_chat_analysis.io import read_conversations


def audit(bundle, conversations):
    config,cases=load_bundle(bundle)
    raw=read_conversations(conversations,cases)
    records=[]
    for sid,case in cases.items():
        source=raw[sid]
        rebuilt=make_case({'session_id':sid},source,{},42)
        if case['events']!=rebuilt['events']:
            raise ValueError('Frozen events differ from full selected source events: '+sid)
        source=sorted(source,key=lambda event:int(event.get('turn_number') or 0))
        starts=[i for i,event in enumerate(source) if event['turn_type']=='user_prompt' and not event.get('is_continuation')]
        gaps=[];covered=0
        for index,start in enumerate(starts):
            end=starts[index+1] if index+1<len(starts) else len(source)
            segment=source[start+1:end]
            counts=Counter(event['turn_type'] for event in segment)
            if any(counts[k] for k in ('assistant_response','tool_use','tool_result')):
                covered+=1
            else:
                gaps.append({'source_prompt_turn':source[start]['turn_number'],
                             'next_source_prompt_turn':source[end]['turn_number'] if end<len(source) else None,
                             'intervening_source_event_types':dict(counts)})
        records.append({'case_id':sid,'agent':case['agent'],'user_messages':len(starts),
                        'segments_with_agent_or_tool_records':covered,'segments_without_visible_response':len(gaps),
                        'gaps':gaps,'source_match':True})
    return {'package_id':config['package_id'], 'summary':{'sessions':len(records),
        'user_messages':sum(r['user_messages'] for r in records),
        'segments_with_agent_or_tool_records':sum(r['segments_with_agent_or_tool_records'] for r in records),
        'segments_without_visible_response':sum(r['segments_without_visible_response'] for r in records),
        'sessions_with_at_least_one_gap':sum(bool(r['gaps']) for r in records),
        'source_event_match_count':len(records)},
        'interpretation':'A segment runs from one non-continuation user message to the next, or to the end of the recorded session. It is not guaranteed to be a causal request-response pair. No visible response does not prove the agent ignored the request. Tool-only segments do not prove completion. Frozen selected event types exactly match the source parquet; source data itself may omit events or truncate tool results.',
        'cases':records}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--bundle',type=Path,default=Path('annotation_release'))
    parser.add_argument('--source',type=Path,default=Path('data/swe-chat/conversations.parquet'))
    parser.add_argument('--output',type=Path,default=Path('annotation_release/trace_audit.json'))
    args=parser.parse_args()
    result=audit(args.bundle,args.source)
    path=args.output
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result['summary'],ensure_ascii=False));print(path)
