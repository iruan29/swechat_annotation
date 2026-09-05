from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from swe_chat_analysis.cli import _check_study1_output_version
from swe_chat_analysis.io import read_jsonl, write_jsonl
from swe_chat_analysis.study1 import (
    _comparison, _is_delayed, aggregate_study1, derive_behavior_mode,
    normalize_requirements_annotation, validate_behavior_annotation, validate_requirements_annotation,
)


def requirements():
    return {
        "confidence": 0.9,
        "task_threads": [{
            "task_id": "task_1", "initial_instruction_turn": 0,
            "initial_requirements": ["export"],
            "initial_instruction_specificity": {
                "score": 2, "explicit_final_requirement_ids": ["R1"], "missing_final_requirement_ids": ["R2"],
            },
            "final_requirements": [
                {"requirement_id": "R1", "basis": "project_grounded", "present_in_initial_instruction": True, "evidence_turns": [0]},
                {"requirement_id": "R2", "basis": "project_grounded", "present_in_initial_instruction": False, "evidence_turns": [1, 4]},
            ],
            "requirement_events": [{
                "requirement_id": "R2", "turn": 4, "first_explicit_turn": 4,
                "first_user_requirement_turn": 4, "proactive_question_turn": None,
                "requirement_change": "new_requirement", "event_type": "requirement_revelation",
                "same_task": True, "material": True, "articulation_source": "user",
                "requirement_basis": "project_grounded", "basis_evidence_turns": [1, 4],
                "user_requirement_trigger": "execution_error", "causal_link_strength": "strong",
                "trigger_turns": [1], "discovery_status": "became_discoverable_later",
                "earliest_discoverable_turn": 1, "inferable_before_revelation": True,
                "discovery_evidence_path": [{"turn": 1, "source": "execution_error"}, {"turn": 4, "source": "user_update"}],
                "agent_recognition_turn": 5, "correct_implementation_turn": 6,
                "implementation_status": "satisfied", "agent_response": "correctly_updated_after_new_evidence",
                "regressed_requirement_ids": [], "response_evidence_turns": [3, 5, 6], "evidence_turns": [1, 4, 5, 6],
            }],
            "evidence_sufficient": True, "evolution_evidence_sufficient": True,
            "implementation_evidence_sufficient": True,
            "literal_initial_completion_satisfies_final_requirements": False,
        }],
    }


def validate(value):
    validate_requirements_annotation(value, set(range(9)), {0, 4, 8})


def row(value, session="s"):
    return {"session_id": session, "annotation": value, "observed_costs": {"human_rework_lines": 10}}


class Study1V6Tests(unittest.TestCase):
    def test_anticipation_separates_recognition_from_satisfaction(self):
        value = requirements()
        event = value["task_threads"][0]["requirement_events"][0]
        event.update(agent_recognition_turn=3, agent_response="anticipated_and_satisfied")
        with self.assertRaisesRegex(ValueError, "implementation timing"):
            validate(value)
        normalize_requirements_annotation(value)
        validate(value)
        self.assertEqual(event["agent_response"], "anticipated_then_satisfied_after_instruction")
        self.assertFalse(_is_delayed(event, 0))
        event["correct_implementation_turn"] = 3
        normalize_requirements_annotation(value)
        validate(value)
        self.assertEqual(event["agent_response"], "anticipated_and_satisfied")

    def test_success_and_question_need_observed_evidence(self):
        value = requirements()
        event = value["task_threads"][0]["requirement_events"][0]
        event.update(agent_response="proactive_question_then_satisfied")
        with self.assertRaisesRegex(ValueError, "evidenced question"):
            validate(value)
        event["proactive_question_turn"] = 3
        validate(value)
        event["correct_implementation_turn"] = None
        with self.assertRaisesRegex(ValueError, "successful response"):
            validate(value)

    def test_derived_fields_do_not_require_paid_repair(self):
        value = requirements()
        thread = value["task_threads"][0]
        thread["initial_instruction_specificity"]["missing_final_requirement_ids"] = []
        thread["requirement_events"][0]["inferable_before_revelation"] = False
        normalize_requirements_annotation(value)
        validate(value)
        self.assertEqual(thread["initial_instruction_specificity"]["missing_final_requirement_ids"], ["R2"])
        self.assertTrue(thread["requirement_events"][0]["inferable_before_revelation"])

    def test_ambiguous_tool_source_is_not_silently_guessed(self):
        value = requirements()
        value["task_threads"][0]["requirement_events"][0]["discovery_evidence_path"][0]["source"] = "tool"
        normalize_requirements_annotation(value)
        with self.assertRaisesRegex(ValueError, "source='tool'"):
            validate(value)

    def test_existing_requirement_repair_is_not_emergence(self):
        value = requirements()
        event = value["task_threads"][0]["requirement_events"][0]
        event.update(requirement_id="R1")
        with self.assertRaisesRegex(ValueError, "initially explicit"):
            validate(value)
        event.update(requirement_change="existing_requirement_correction", first_explicit_turn=0,
                     first_user_requirement_turn=0, earliest_discoverable_turn=0,
                     inferable_before_revelation=False, discovery_status="explicit_initially",
                     discovery_evidence_path=[{"turn": 0, "source": "initial_instruction"}])
        validate(value)
        summary = aggregate_study1([row(value)], [])
        self.assertEqual(summary["material_requirement_emergence_rate"]["numerator"], 0)
        self.assertEqual(summary["terminal_requirement_discovery"]["earlier_discoverable_rate"]["denominator"], 0)
        self.assertEqual(summary["agent_response_to_evolving_project_evidence"]["existing_requirement_correction_count"], 1)

    def test_temporal_and_discovery_status_conflicts_are_rejected(self):
        for updates in ({"discovery_status": "explicit_initially"}, {"first_explicit_turn": 8},
                        {"first_user_requirement_turn": 3}, {"correct_implementation_turn": 3},
                        {"earliest_discoverable_turn": 5}, {"discovery_status": "discoverable_initially"}):
            value = requirements()
            value["task_threads"][0]["requirement_events"][0].update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate(value)

    def test_repeated_requirement_is_not_counted_as_another_discovery(self):
        value = requirements()
        events = value["task_threads"][0]["requirement_events"]
        repeated = deepcopy(events[0])
        events.append(repeated)
        with self.assertRaisesRegex(ValueError, "more than once"):
            validate(value)
        repeated.update(turn=8, first_explicit_turn=8)
        with self.assertRaisesRegex(ValueError, "consistent first_explicit_turn"):
            validate(value)

    def test_requirements_do_not_depend_on_implementation_or_evolution_verification(self):
        value = requirements()
        thread = value["task_threads"][0]
        thread.update(implementation_evidence_sufficient=False, evolution_evidence_sufficient=False,
                      literal_initial_completion_satisfies_final_requirements=None)
        thread["requirement_events"][0].update(implementation_status="unknown", correct_implementation_turn=None,
                                              agent_response="unclear_or_unresolved")
        normalize_requirements_annotation(value)
        validate(value)
        summary = aggregate_study1([row(value)], [])
        self.assertEqual(summary["initial_instruction_requirement_coverage"]["estimate"], 0.5)
        self.assertEqual(summary["material_requirement_emergence_rate"]["denominator"], 0)
        self.assertEqual(summary["literal_initial_instruction_satisfies_final_requirements_rate"]["denominator"], 0)
        self.assertEqual(summary["cost_of_delayed_project_understanding"]["excluded_unknown_exposure_session_count"], 1)

    def test_unknown_recognition_is_not_a_known_cost_group(self):
        value = requirements()
        value["task_threads"][0]["requirement_events"][0]["agent_recognition_turn"] = None
        validate(value)
        cost = aggregate_study1([row(value)], [])["cost_of_delayed_project_understanding"]
        self.assertEqual(cost["exposed_session_count"], 0)
        self.assertEqual(cost["unexposed_session_count"], 0)
        self.assertEqual(cost["excluded_unknown_exposure_session_count"], 1)

    def test_novelty_gate_rejects_user_supplied_diagnosis_as_level3(self):
        value = {
            "episode_in_scope": True, "instruction_turn": 0, "classification_evidence_sufficient": True,
            "project_reasoning_opportunity": True, "important_uncertainty_identified": True,
            "resolution_methods": ["repository_evidence"], "instruction_scope_preserved": True,
            "project_evidence_used": True, "unstated_material_requirement_or_downstream_impact_identified": True,
            "material_plan_scope_strategy_or_acceptance_affected": True, "proactive_before_explicit_correction": False,
            "requirement_novelty": "already_requested", "novel_requirement": "", "material_change": "",
            "novelty_evidence_turns": [], "evidence": [{"turn": 1, "speaker_or_source": "assistant"}],
        }
        validate_behavior_annotation(value, 0, {0, 1})
        self.assertEqual(value["behavior_mode"], "instruction_scoped_sensemaking")
        value.update(requirement_novelty="new_material_requirement", novel_requirement="additional acceptance constraint",
                     material_change="new acceptance test", novelty_evidence_turns=[1])
        validate_behavior_annotation(value, 0, {0, 1})
        self.assertEqual(value["behavior_mode"], "project_level_requirement_discovery")
        value["novelty_evidence_turns"] = [0]
        with self.assertRaisesRegex(ValueError, "during the target episode"):
            validate_behavior_annotation(value, 0, {0, 1})
        value["requirement_novelty"] = "unclear"
        derive_behavior_mode(value)
        self.assertEqual(value["behavior_mode"], "unclear")

    def test_outlier_sensitivity_retains_all_data_and_exposes_sign_changes(self):
        exposed, comparator = [1160, 12, 7], [30, 34]
        result = _comparison(exposed, comparator)
        self.assertEqual(result["delayed_project_understanding"]["n"], 3)
        self.assertGreater(result["delayed_project_understanding"]["largest_value_share_of_total"], 0.97)
        self.assertTrue(result["leave_one_session_out_mean_difference"]["sign_changes"])
        self.assertEqual(exposed, [1160, 12, 7])
        self.assertIsNone(_comparison([None], [0])["mean_difference_delayed_minus_not_delayed"])
        self.assertIsNone(_comparison([1], [2])["leave_one_session_out_mean_difference"]["min"])

    def test_old_pilot_is_not_overwritten_by_resume(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "requirement_annotations.jsonl"
            old = {"rubric_version": "requirement_evolution_v5"}
            write_jsonl(path, [old])
            with self.assertRaisesRegex(RuntimeError, "NEW output directory"):
                _check_study1_output_version(root, True)
            self.assertEqual(read_jsonl(path), [old])
