import unittest
from swe_chat_analysis.human import make_case
from swe_chat_analysis.human_interactions import analyze
from swe_chat_analysis.human_relevance import assess


def case(prompts, replies):
    events=[]
    for i,(u,a) in enumerate(zip(prompts,replies)):
        events.extend([dict(turn_number=i*2,turn_type='user_prompt',content=u),dict(turn_number=i*2+1,turn_type='assistant_response',content=a)])
    c=make_case({'session_id':'s'},events,{},42)
    c['interaction_quality']=analyze([(e['turn'],e['kind'],False,e['text'],len(e['text']),bool(e['text'])) for e in c['events']])
    return c


class RelevanceTests(unittest.TestCase):
    def test_requires_visible_request_and_agent_evidence(self):
        c=case(['Fix the export.', 'I meant CSV, not PDF. We need compatibility with our old reader.', 'I thought the API accepted both formats; can we keep the existing schema?'],
               ['Could you clarify which export format you want? The reader currently only supports PDF.', 'The existing reader requires CSV. I will adjust the exporter while preserving the current field names.', 'The constraint is the API schema. I have retained the existing fields and checked the CSV output.'])
        a=assess(c)
        self.assertTrue(a['eligible'])
        self.assertEqual(len(a['evidence']),2)
        self.assertTrue(all(e['assistant_turn']>e['user_turn'] for e in a['evidence']))
        self.assertNotIn('initial_instruction_wrong',a)

    def test_workflow_chatter_does_not_qualify(self):
        c=case(['Create a basic report page.', 'commit and push', 'create a PR please'],['I have completed the requested report page and verified that the app still builds correctly.']*3)
        self.assertFalse(assess(c)['eligible'])

    def test_user_cues_without_visible_agent_response_do_not_qualify(self):
        c=case(['Fix the export.', 'Actually I want a new format instead of this one.', 'I thought the API required CSV but the schema is different.'],['Starting implementation now.','',''])
        self.assertFalse(assess(c)['eligible'])

    def test_api_error_is_not_an_agent_response(self):
        c=case(['Fix the export.', 'I meant CSV, not PDF. We need compatibility with our old reader.', 'I thought the API accepted both formats; can we keep the existing schema?'],['API Error: 500 {"type":"api_error","message":"Internal server error with no model response"}']*3)
        self.assertFalse(assess(c)['eligible'])
