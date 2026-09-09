from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from swe_chat_analysis.human import digest, make_case
from swe_chat_analysis import human_simple as simple
from swe_chat_analysis.human_team import build, export, load_bundle, local_project, merge, RATERS, write_json
from swe_chat_analysis.io import write_jsonl
from test_human_simple import annotation


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'source'
        source.mkdir()
        events = [dict(turn_number=t, turn_type='user_prompt' if t % 3 == 0 else 'assistant_response', content=f'Evidence request {t}') for t in range(24)]
        cases = []
        for i in range(100):
            case = make_case(dict(session_id=f's{i:03}', repo_id='r', agent='agent'), events, {}, 42)
            case['reading_stats'] = dict(user_rounds=8, characters=128, events=16)
            case['input_fingerprint'] = digest({k:v for k,v in case.items() if k != 'input_fingerprint'})
            cases.append(case)
        write_jsonl(source / 'cases.jsonl', cases)
        write_json(source / 'manifest.json', dict(human_version=simple.VERSION, rubric_versions={'review':simple.VERSION}, session_count=100,
                   case_fingerprints={c['case_id']:c['input_fingerprint'] for c in cases}))
        self.bundle = self.root / 'bundle'
        build(source, self.bundle, Path(__file__).resolve().parents[1])

    def complete(self, rater, count=None):
        p=local_project(self.bundle, rater)
        for case in list(p.cases.values())[:count]:
            p.save(rater, case['case_id'], 'review', 0, annotation(), True)
        path=self.root / f'{rater}.json'
        export(self.bundle, rater, path, allow_partial=count is not None)
        return path

    def test_portable_split_and_identity(self):
        config, cases = load_bundle(self.bundle)
        self.assertEqual([len(config['assignments'][r]) for r in RATERS], [100,100,100])
        self.assertEqual(len(cases),100)
        self.assertEqual(config["assignments"]["rater_a"], config["assignments"]["rater_b"])
        self.assertEqual(config["assignments"]["rater_a"], config["assignments"]["rater_c"])
        # -S removes third-party site packages: the delivered runtime is stdlib only.
        result=subprocess.run([sys.executable,'-S',str(self.bundle/'annotate.py'),'verify'], capture_output=True, text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(any(self.bundle.glob('assignments/**/*.sqlite3')))
        p=local_project(self.bundle,'rater_a')
        with self.assertRaises(ValueError): p.task_list('rater_b')
        p.save('rater_a', next(iter(p.cases)), 'review', 0, {'notes':'draft'}, False)
        resumed=local_project(self.bundle,'rater_a')
        self.assertEqual(resumed.rows('rater_a')[0]['status'],'draft')
        with self.assertRaises(ValueError): export(self.bundle,'rater_a')

    def test_complete_merge_recalculates_metrics_and_preserves_all(self):
        paths=[self.complete(r) for r in RATERS]
        payload=json.loads(paths[0].read_text())
        payload['annotations']['review'][0]['metrics']['api_call_count']=999999
        write_json(paths[0],payload)
        output=self.root/'merged'
        result=merge(self.bundle, paths, output)
        self.assertTrue(result['run_completeness']['complete'])
        merged=json.loads((output/'merged.json').read_text())
        self.assertEqual(len(merged['annotations']['review']),300)
        self.assertIsNone(merged['annotations']['review'][0]['metrics']['api_call_count'])
        self.assertEqual(len((output/'analysis.csv').read_text(encoding='utf-8-sig').splitlines()),301)
        with self.assertRaises(ValueError): merge(self.bundle,paths,output)

    def test_incomplete_duplicate_wrong_batch_wrong_evidence_rejected(self):
        path=self.complete('rater_a',1)
        with self.assertRaises(ValueError): merge(self.bundle,[path],self.root/'missing')
        report=merge(self.bundle,[path],self.root/'interim',True)
        self.assertEqual(report['run_completeness']['completed'],1)
        with self.assertRaises(ValueError): merge(self.bundle,[path,path],self.root/'duplicate',True)
        original=json.loads(path.read_text())
        mutations=[lambda p:p['delivery'].update(package_id='wrong'),
                   lambda p:p['annotations']['review'][0].update(annotator='rater_b'),
                   lambda p:p['annotations']['review'][0]['annotation']['gap'].update(evidence_turns=[999]),
                   lambda p:p['annotations']['review'].append(deepcopy(p['annotations']['review'][0])),
                   lambda p:p['delivery'].update(complete=True)]
        for i,mutate in enumerate(mutations):
            payload=deepcopy(original);mutate(payload);bad=self.root/f'bad{i}.json';write_json(bad,payload)
            with self.assertRaises(ValueError):merge(self.bundle,[bad],self.root/f'out{i}',True)
            self.assertFalse((self.root/f'out{i}').exists())

    def test_one_complete_rater_is_not_complete_team(self):
        path = self.complete("rater_a")
        with self.assertRaises(ValueError): merge(self.bundle, [path], self.root/"incomplete_team")
        report = merge(self.bundle, [path], self.root/"partial_team", True)
        self.assertEqual(report["run_completeness"]["completed"], 100)
        self.assertEqual(len(report["run_completeness"]["missing_assignments"]), 200)

    def test_frozen_assignment_tamper_rejected(self):
        path=self.bundle/'assignments'/'rater_a'/'cases.jsonl'
        text=path.read_text().replace('Evidence','Changed',1);path.write_text(text)
        with self.assertRaises(ValueError):load_bundle(self.bundle)


if __name__=='__main__':unittest.main()
