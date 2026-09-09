import unittest
from swe_chat_analysis.human_interactions import analyze, prompt_reason


def row(turn, kind, text, continuation=False):
    return (turn, kind, continuation, text, len(text), bool(text.strip()))


class InteractionTests(unittest.TestCase):
    def test_real_exchanges_allow_more_than_twelve(self):
        events = [row(i, 'user_prompt' if i % 2 == 0 else 'assistant_response', f'Please implement requirement {i}') for i in range(34)]
        q = analyze(events)
        self.assertEqual(q['effective_interactions'], 17)
        self.assertEqual(q['answered_effective_interactions'], 17)

    def test_template_split_is_not_eight_exchanges(self):
        template = 'You are a code reviewer. Your job is to review code changes and provide actionable feedback.'
        events = [row(0, 'user_prompt', template)] + [row(i, 'user_prompt', f'Section number {i}') for i in range(1, 8)] + [row(9, 'assistant_response', 'Review done')]
        q = analyze(events)
        self.assertTrue(q['template_session'])
        self.assertLess(q['effective_interactions'], 8)

    def test_consecutive_users_share_one_exchange(self):
        q = analyze([row(0, 'user_prompt', 'Build search'), row(1, 'user_prompt', 'Also support Chinese'), row(2, 'tool_use', 'Search files'), row(3, 'user_prompt', 'Add keyboard navigation'), row(4, 'assistant_response', 'Added')])
        self.assertEqual(q['effective_interactions'], 2)
        self.assertEqual(q['exchanges'][0]['substantive_turns'], [0, 1])

    def test_automated_events_cannot_inflate_count(self):
        events = [row(0, 'user_prompt', 'Build search'), row(1, 'assistant_response', 'Started')]
        for i, text in enumerate(['yes', 'Tool loaded.', '<objective>Show project progress and propose next steps</objective>', 'Stop hook feedback: please fix this', '<teammate-message teammate_id="x">Build more</teammate-message>', 'Continue from where you left off.'], 1):
            events += [row(i*2, 'user_prompt', text), row(i*2+1, 'assistant_response', 'Working')]
        self.assertEqual(analyze(events)['effective_interactions'], 1)

    def test_duplicate_requests_do_not_count_again(self):
        q = analyze([row(0, 'user_prompt', 'Add search [Image #1]'), row(1, 'assistant_response', 'Done'), row(2, 'user_prompt', 'Add search [Image #2]'), row(3, 'assistant_response', 'Done')])
        self.assertEqual(q['effective_interactions'], 1)
        self.assertEqual(q['excluded_prompt_counts']['duplicate_prompt'], 1)

    def test_continuation_and_empty_activity_are_not_exchanges(self):
        q = analyze([row(0,'user_prompt','Build search'),row(1,'assistant_response','  '),row(2,'user_prompt','Compacted context',True)])
        self.assertEqual(q['effective_interactions'],0)
        self.assertEqual(q['raw_user_messages'],1)

    def test_concise_preferences_remain_substantive(self):
        for prompt in ['不要发布到 Chrome，只发布 Edge', 'use blue', 'name is required for metadata', 'git status', '英語ではなく日本語に変更して', '不要这个颜色']:
            self.assertIsNone(prompt_reason(prompt),prompt)

    def test_initial_environment_wrapper_is_not_eligible(self):
        q=analyze([row(0,'user_prompt','<system_instruction>Shared environment</system_instruction>\nBuild search'),row(1,'assistant_response','Done')])
        self.assertFalse(q['first_prompt_substantive'])

    def test_order_is_source_turn_not_input_order(self):
        q=analyze([row(41,'assistant_response','Done'),row(0,'user_prompt','Build search')])
        self.assertEqual(q['effective_interactions'],1)
        self.assertEqual(q['exchanges'][0]['activity_turns'],[41])
