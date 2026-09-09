from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from swe_chat_analysis import human_simple as simple
from swe_chat_analysis.human import HumanProject, Conflict, digest, make_case
from swe_chat_analysis.human_schema import blank
from swe_chat_analysis.io import write_jsonl
from swe_chat_analysis.human_sampling import scan
import pyarrow as pa
import pyarrow.parquet as pq


def annotation():
    return dict(evolution=dict(initial_coverage='一部分', new_requirements='有', source='项目需求', first_new_turn=3, behaviors=['收到新证据后正确更新']),
                gap=dict(instruction_quality='不完整', driver='无法判断', literal_feasibility='只能部分达成', response='用户指出后才调整'))


class SimpleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = [dict(session_id='s', turn_number=t, turn_type=k, content='text', is_continuation=False) for t, k in enumerate(['user_prompt', 'assistant_response', 'tool_use', 'user_prompt', 'assistant_response', 'tool_use'])]
        self.case = make_case(dict(session_id='s', agent='a', repo_id='r'), self.events, {}, 42)
        write_jsonl(self.root / 'cases.jsonl', [self.case])
        (self.root / 'manifest.json').write_text(json.dumps(dict(human_version=simple.VERSION, rubric_versions={simple.STAGE: simple.VERSION}, session_count=1, case_fingerprints={'s': self.case['input_fingerprint']})))
        self.project = HumanProject(self.root)

    def test_full_trace_revision_and_export(self):
        view = self.project.case_view('a', 's', 'review')
        self.assertEqual(len(view['events']), 6)
        self.assertEqual(view['annotation'], blank(simple.schema()))
        self.assertEqual(self.project.task_list('a')['stages'], ['review'])
        self.project.save('a', 's', 'review', 0, annotation(), True)
        result = self.project.export('a')
        metrics = result['annotations']['review'][0]['metrics']
        self.assertEqual(metrics['user_rounds'], 2)
        self.assertEqual(metrics['tool_events_from_first_update'], 1)
        self.assertIsNone(metrics['api_call_count'])
        self.assertTrue(metrics['late_requirement'])
        self.project.save('a', 's', 'review', 1, annotation(), True)
        with self.assertRaises(Conflict):
            self.project.save('a', 's', 'review', 1, annotation(), True)
        self.assertEqual(self.project.export('b')['summary']['run_completeness']['completed'], 0)
        self.project.save('a', 's', 'review', 2, annotation(), False)
        self.assertEqual(self.project.export('a')['summary']['run_completeness']['completed'], 0)

    def test_conditional_fields_and_single_cause_validation(self):
        simple.validate(annotation(), self.case['events'])
        for mutate in [lambda a: a['evolution'].update(first_new_turn=99),
                       lambda a: a['evolution'].update(first_new_turn=0),
                       lambda a: a['evolution'].update(first_new_turn=4),
                       lambda a: a['evolution'].update(source=None),
                       lambda a: a['evolution'].update(new_requirements='没有'),
                       lambda a: a['gap'].update(driver=['无法判断']),
                       lambda a: a['gap'].update(driver='不适用')]:
            value=annotation();mutate(value)
            with self.assertRaises(ValueError): simple.validate(value,self.case['events'])
        for answer,expected in [('没有',False),('无法判断',None)]:
            value=annotation();value['evolution'].update(new_requirements=answer,source=None,first_new_turn=None)
            simple.validate(value,self.case['events'])
            self.assertIs(simple.costs(self.case,value)['late_requirement'],expected)
        self.assertIsNone(simple.costs(self.case,annotation())['requirement_update_count'])

    def test_form_has_no_text_questions_and_no_project_overview(self):
        spec=simple.schema()
        self.assertEqual(set(spec['properties']),{'evolution','gap'})
        def visit(node):
            if node['type']=='string': self.assertIn('enum',node)
            for child in node.get('properties',{}).values():visit(child)
            if 'items' in node:visit(node['items'])
        visit(spec)
        self.assertEqual(spec['properties']['gap']['properties']['driver']['type'],'string')

    def test_scan_counts_actual_prompts_and_full_text(self):
        events = deepcopy(self.events)
        events.append(dict(session_id='s', turn_number=6, turn_type='user_prompt', content='continuation', is_continuation=True))
        path = self.root / 'conversations.parquet'
        pq.write_table(pa.Table.from_pylist(events), path)
        stats = scan(path)['s']
        case = make_case(dict(session_id='s'), events, {}, 42)
        self.assertEqual(stats['user_rounds'], 2)
        self.assertEqual(stats['characters'], sum(len(e['text']) for e in case['events']))

    def test_prepare_reproducible_observed_bounds_and_no_overwrite(self):
        from argparse import Namespace
        from swe_chat_analysis.human_sampling import prepare
        sessions = [dict(session_id=sid, prompt_count=999) for sid in ('a', 'b', 'c')]
        events = [dict(row, session_id=sid, content=row['content'] + ' ' + sid + ' ' + str(row['turn_number'])) for sid in ('a', 'b', 'c') for row in self.events]
        # Metadata says 999 prompts, but actual observed count is two.
        pq.write_table(pa.Table.from_pylist(sessions), self.root / 'sessions.parquet')
        pq.write_table(pa.Table.from_pylist(events), self.root / 'conversations.parquet')
        args = Namespace(data_dir=str(self.root), output_dir=str(self.root / 'one'), seed=42,
                         sample_size=2, min_prompts=2, max_prompts=2, min_chars=1, max_chars=1000, max_events=20)
        prepare(args)
        first = (Path(args.output_dir) / 'cases.jsonl').read_text()
        with self.assertRaises(ValueError): prepare(args)
        args.output_dir = str(self.root / 'two'); prepare(args)
        self.assertEqual(first, (Path(args.output_dir) / 'cases.jsonl').read_text())
        args.output_dir = str(self.root / 'too_many'); args.sample_size = 4
        with self.assertRaises(ValueError): prepare(args)
        self.assertFalse(Path(args.output_dir).exists())

    def test_missing_costs_excluded(self):
        self.project.save('a', 's', 'review', 0, annotation(), True)
        stats = self.project.export('a')['summary']['cost_comparison']['有晚出现需求']
        self.assertEqual(stats['sessions'], 1)
        self.assertEqual(stats['api_call_count'], dict(n=0, mean=None, median=None))


if __name__ == '__main__':
    unittest.main()
