from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from swe_chat_analysis.human import HUMAN_VERSION, Conflict, HumanProject, digest, handler, make_case
from swe_chat_analysis.human_schema import VERSIONS, blank, schema, validate
from swe_chat_analysis.io import write_jsonl
from test_study1_v6 import requirements


def behavior(target=0):
    value = blank(schema("behavior"))
    for key, child in schema("behavior")["properties"].items():
        if child["type"] == "boolean":
            value[key] = False
    value.update(instruction_turn=target, episode_in_scope=True, classification_evidence_sufficient=True,
                 instruction_summary="export", opportunity_reason="No material ambiguity", rationale="Direct response",
                 requirement_novelty="not_applicable",
                 evidence=[{"turn": 1, "speaker_or_source": "assistant", "quote_or_paraphrase": "Doing export"}])
    return value


def human_requirements():
    value = requirements()

    def fill(spec, item):
        if spec["type"] == "object":
            for key, child in spec["properties"].items():
                item[key] = fill(child, item.get(key, blank(child)))
        elif spec["type"] == "array":
            item = [fill(spec["items"], child) for child in item]
        elif spec["type"] == "string" and not item:
            item = "Supporting evidence"
        return item

    return fill(schema("requirements"), value)


class HumanTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        events = [{"turn_number": turn, "turn_type": "user_prompt" if turn in {0, 4, 8} else "assistant_response",
                   "content": "FUTURE SECRET" if turn == 8 else f"Text {turn}", "is_continuation": False}
                  for turn in range(9)]
        self.case = make_case({"session_id": "s", "repo_id": "r", "agent": "a"}, events, {}, 42)
        self.case["target_instruction_turn"] = 0
        self.case["input_fingerprint"] = digest({key: value for key, value in self.case.items() if key != "input_fingerprint"})
        write_jsonl(self.root / "cases.jsonl", [self.case])
        self.manifest = {"human_version": HUMAN_VERSION, "rubric_versions": VERSIONS, "session_count": 1,
                         "case_fingerprints": {"s": self.case["input_fingerprint"]}}
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))
        self.project = HumanProject(self.root)

    def test_prefix_and_server_phase_gating(self):
        view = self.project.case_view("alice", "s", "behavior")
        self.assertNotIn("FUTURE SECRET", json.dumps(view))
        self.assertNotIn("observed_costs", view)
        self.assertEqual(view["commits"], [])
        with self.assertRaises(Conflict):
            self.project.case_view("alice", "s", "requirements")
        with self.assertRaises(Conflict):
            self.project.save("alice", "s", "study2", 0, {}, True)
        self.project.save("alice", "s", "behavior", 0, behavior(), True)
        self.assertIn("FUTURE SECRET", json.dumps(self.project.case_view("alice", "s", "requirements")))

    def test_completed_behavior_is_immutable_and_raters_are_separate(self):
        self.project.save("alice", "s", "behavior", 0, behavior(), True)
        with self.assertRaises(Conflict):
            self.project.save("alice", "s", "behavior", 1, behavior(), True)
        self.assertEqual(self.project.case_view("bob", "s", "behavior")["status"], "new")
        with self.assertRaises(Conflict):
            self.project.case_view("bob", "s", "requirements")

    def test_draft_resume_history_and_optimistic_lock(self):
        self.project.save("alice", "s", "behavior", 0, {"rationale": "unfinished"}, False)
        reloaded = HumanProject(self.root)
        self.assertEqual(reloaded.case_view("alice", "s", "behavior")["annotation"]["rationale"], "unfinished")
        with self.assertRaises(Conflict):
            reloaded.save("alice", "s", "behavior", 0, behavior(), False)
        reloaded.save("alice", "s", "behavior", 1, behavior(), True)
        with reloaded.connect() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM history").fetchone()[0], 2)

    def test_unanswered_boolean_is_not_normalized_to_false(self):
        value = behavior()
        value["important_uncertainty_identified"] = None
        with self.assertRaisesRegex(ValueError, "未回答不会自动视为否"):
            self.project.save("alice", "s", "behavior", 0, value, True)
        self.assertEqual(self.project.rows("alice"), [])

    def test_behavior_cannot_cite_future_evidence(self):
        value = behavior()
        value["evidence"][0]["turn"] = 8
        with self.assertRaisesRegex(ValueError, "absent from prefix"):
            self.project.save("alice", "s", "behavior", 0, value, True)

    def test_neutral_form_defaults_and_source_enums(self):
        for stage in VERSIONS:
            value = blank(schema(stage))
            self.assertNotIn("the requested local optimization", json.dumps(value))
        self.assertIsNone(blank(schema("behavior"))["episode_in_scope"])
        self.assertNotIn("inferable_before_revelation", str(schema("requirements")))

    def test_full_trace_is_not_clipped_and_continuations_are_not_targets(self):
        events = [{"turn_number": 0, "turn_type": "user_prompt", "is_continuation": True, "content": "summary"},
                  {"turn_number": 1, "turn_type": "user_prompt", "content": "x" * 10000},
                  {"turn_number": 2, "turn_type": "assistant_response", "content": "y" * 10000, "prompt_pushback": "secret label"}]
        case = make_case({"session_id": "long", "session_success": "secret label"}, events, {}, 42)
        self.assertEqual(case["target_instruction_turn"], 1)
        self.assertEqual(len(case["events"][1]["text"]), 10000)
        self.assertNotIn("secret label", json.dumps(case))
        self.assertEqual(case, make_case({"session_id": "long", "session_success": "secret label"}, events, {}, 42))

    def test_duplicate_turns_are_reindexed_consistently(self):
        events = [{"turn_number": 1, "turn_type": "user_prompt", "content": "first"},
                  {"turn_number": 1, "turn_type": "assistant_response", "content": "second"}]
        case = make_case({"session_id": "duplicate"}, events, {}, 42)
        self.assertEqual([event["turn"] for event in case["events"]], [0, 1])
        self.assertEqual([event["source_turn"] for event in case["events"]], [1, 1])

    def test_project_fingerprint_and_versions_are_frozen(self):
        tampered = deepcopy(self.case)
        tampered["events"][0]["text"] = "changed"
        write_jsonl(self.root / "cases.jsonl", [tampered])
        with self.assertRaisesRegex(ValueError, "冻结样本已变更"):
            HumanProject(self.root)

    def test_reuses_study_metrics_and_excludes_drafts(self):
        self.project.save("alice", "s", "behavior", 0, behavior(), True)
        self.project.save("alice", "s", "requirements", 0, human_requirements(), True)
        self.project.save("alice", "s", "study2", 0, {}, False)
        exported = self.project.export("alice")
        self.assertEqual(exported["summary"]["study1"]["initial_instruction_requirement_coverage"]["estimate"], 0.5)
        self.assertEqual(exported["summary"]["run_completeness"]["fully_completed_session_count"], 0)
        self.assertEqual(exported["annotations"]["study2"], [])
        self.assertEqual(exported["annotations"]["requirements"][0]["annotation_source"], "human")

    def test_study2_unidentifiable_situation_has_explicit_na_fields(self):
        spec = schema("study2")
        value = blank(spec)
        thread = blank(spec["properties"]["task_threads"]["items"])
        thread.update(task_id="task_1", surface_instruction="export", surface_instruction_turn=0,
                      actual_situation_identifiable=False, user_belief_identifiable=False, rationale="No confirming evidence")
        value.update(task_threads=[thread], confidence=0.5)
        normalized = validate("study2", value, self.case["events"], 0)
        self.assertFalse(normalized["task_threads"][0]["material_instruction_reality_mismatch"])
        self.assertEqual(normalized["task_threads"][0]["agent_gap_response"]["observed_resolution_status"], "unknown")
        self.assertIsNone(value["task_threads"][0]["material_instruction_reality_mismatch"])

    def test_agreement_uses_matched_episodes_and_handles_degeneracy(self):
        self.project.save("alice", "s", "behavior", 0, behavior(), True)
        self.project.save("bob", "s", "behavior", 0, behavior(), True)
        pair = self.project.agreement()["pairs"][0]
        self.assertEqual(pair["agreement"], 1)
        self.assertIsNone(pair["cohen_kappa"])
        self.assertEqual(pair["paired_case_count"], 1)

    def test_invalid_identity_does_not_become_export_path(self):
        with self.assertRaises(ValueError):
            self.project.export("../../escape")

    def test_http_auth_static_assets_and_hidden_future(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.project, "test-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/") as response:
            self.assertIn("人工标注台", response.read().decode())
        with self.assertRaises(HTTPError) as caught:
            urlopen(base + "/api/tasks?annotator=alice")
        self.assertEqual(caught.exception.code, 401)
        request = Request(base + "/api/case?annotator=alice&case_id=s&stage=behavior", headers={"Authorization": "Bearer test-token"})
        with urlopen(request) as response:
            self.assertNotIn("FUTURE SECRET", response.read().decode())
        request = Request(base + "/api/case?annotator=alice&case_id=s&stage=requirements", headers={"Authorization": "Bearer test-token"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
