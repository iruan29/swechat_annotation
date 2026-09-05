from __future__ import annotations

import unittest
from copy import deepcopy
import threading
import time

from swe_chat_analysis.cli import (
    AnnotationValidationFailure, _complete_validated_json, _failure_record,
    _run_concurrent_jobs, build_parser,
)
from swe_chat_analysis.llm import parse_json_object
from swe_chat_analysis.metrics import aggregate
from swe_chat_analysis.packet import (
    behavior_episode_prefixes, build_packet, packet_as_text,
)
from swe_chat_analysis.rubric import (
    derive_behavior_modes, drop_invalid_evidence_turns,
    normalize_null_boolean_fields, validate_annotation,
)
from swe_chat_analysis.study1 import (
    aggregate_study1, derive_behavior_mode, validate_behavior_annotation,
    normalize_behavior_annotation as normalize_study1_behavior,
    normalize_requirements_annotation as normalize_study1_requirements,
    validate_requirements_annotation,
)
from swe_chat_analysis.study2 import (
    aggregate_study2, derive_agent_response_pattern,
    normalize_annotation as normalize_study2_annotation,
    validate_annotation as validate_intent_annotation,
)


def annotation() -> dict:
    return {
        "initial_goal": {"summary": "export", "requirements": ["CSV"]},
        "final_goal": {"summary": "stream export", "requirements": ["CSV", "stream"], "evidence_basis": "dialogue"},
        "material_evolution": {"changed": True, "magnitude": 2, "change_types": ["constraint_added"], "user_driven_change": True, "change_turns": [3], "explanation": "streaming added"},
        "initial_instruction_sufficiency": {"sufficient_for_final_outcome": False, "coverage_score": 2, "would_literal_completion_satisfy_final_requirements": False, "missing_material_requirements": ["streaming"], "explanation": "missing constraint"},
        "behavior_episodes": [{"instruction_turn": 0, "instruction_summary": "export", "project_reasoning_opportunity": True, "opportunity_reason": "existing async exporter", "classification_evidence_sufficient": True, "response_mode": "instruction_scoped_sensemaking", "behavior_level": 2, "important_uncertainty_identified": True, "resolution_methods": ["user_question"], "instruction_scope_preserved": True, "project_evidence_used": False, "unstated_requirement_or_downstream_impact_identified": False, "material_plan_scope_or_acceptance_affected": False, "proactive_before_explicit_correction": False, "rationale": "asked queue question", "evidence": [{"turn": 2, "speaker_or_source": "assistant", "quote_or_paraphrase": "same queue?"}]}],
        "outcome": {"status": "completed", "evidence_source": "commit", "explanation": "commit"},
        "evidence": [{"turn": 3, "speaker_or_source": "user", "quote_or_paraphrase": "must stream", "supports": "constraint"}],
        "confidence": 0.9,
    }


class PipelineTests(unittest.TestCase):
    def test_study_judge_concurrency_is_configurable_and_isolates_errors(self) -> None:
        lock = threading.Lock()
        active = 0
        max_active = 0

        def worker(value: int) -> int:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            if value == 2:
                raise ValueError("expected failure")
            return value * 10

        completed = list(_run_concurrent_jobs([1, 2, 3, 4], worker, workers=3))
        self.assertGreaterEqual(max_active, 2)
        by_job = {job: (result, error) for job, result, error in completed}
        self.assertEqual(by_job[1], (10, None))
        self.assertIsInstance(by_job[2][1], ValueError)
        self.assertEqual(by_job[4], (40, None))

        parser = build_parser()
        self.assertEqual(
            parser.parse_args(["judge-study1", "--workers", "4"]).workers, 4
        )
        self.assertEqual(
            parser.parse_args(["judge-study2", "--concurrency", "3"]).workers, 3
        )

    def test_parse_fenced_json(self) -> None:
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_annotation_and_metrics(self) -> None:
        value = annotation()
        validate_annotation(value)
        result = aggregate([{
            "annotation": value,
            "dataset_prompt_pushback_counts": {"requirement_change": 1},
        }])
        self.assertEqual(result["requirement_evolution_rate"]["estimate"], 1.0)
        self.assertEqual(result["literal_initial_instruction_satisfies_all_final_requirements_rate"]["estimate"], 0.0)
        self.assertEqual(result["behavior_level_distribution"]["instruction_scoped_sensemaking"]["estimate"], 1.0)

    def test_behavior_mode_is_deterministically_derived(self) -> None:
        value = annotation()
        episode = value["behavior_episodes"][0]
        episode.pop("response_mode")
        episode.pop("behavior_level")
        derive_behavior_modes(value)
        self.assertEqual(episode["response_mode"], "instruction_scoped_sensemaking")
        self.assertEqual(episode["behavior_level"], 2)

    def test_relaxed_project_goal_gate(self) -> None:
        value = annotation()
        episode = value["behavior_episodes"][0]
        episode["project_evidence_used"] = True
        episode["unstated_requirement_or_downstream_impact_identified"] = True
        episode["material_plan_scope_or_acceptance_affected"] = True
        episode["proactive_before_explicit_correction"] = False
        derive_behavior_modes(value)
        self.assertEqual(episode["response_mode"], "project_goal_inference")
        self.assertEqual(episode["behavior_level"], 3)

    def test_null_atomic_boolean_is_normalized_to_false(self) -> None:
        value = annotation()
        episode = value["behavior_episodes"][0]
        episode["proactive_before_explicit_correction"] = None
        normalize_null_boolean_fields(value)
        self.assertIs(episode["proactive_before_explicit_correction"], False)

    def test_annotation_rejects_evidence_turn_absent_from_packet(self) -> None:
        value = annotation()
        value["behavior_episodes"][0]["evidence"][0]["turn"] = 9914
        with self.assertRaisesRegex(ValueError, "evidence turns absent from packet"):
            validate_annotation(value, valid_turns={0, 1, 2})

    def test_invalid_evidence_turn_can_be_dropped_with_audit_record(self) -> None:
        value = annotation()
        value["behavior_episodes"][0]["evidence"].append({
            "turn": 9914,
            "speaker_or_source": "tool",
            "quote_or_paraphrase": "commit metadata",
        })
        dropped = drop_invalid_evidence_turns(value, valid_turns={0, 1, 2})
        self.assertEqual(dropped[0]["evidence"]["turn"], 9914)
        validate_annotation(value, valid_turns={0, 1, 2})

    def test_packet_keeps_all_user_prompts(self) -> None:
        session = {"session_id": "s", "prompt_count": 2, "checkpoint_ids": "[]"}
        events = [
            {"turn_number": 0, "turn_type": "user_prompt", "content": "first"},
            {"turn_number": 1, "turn_type": "assistant_response", "content": "x" * 500},
            {"turn_number": 2, "turn_type": "user_prompt", "content": "last"},
        ]
        packet = build_packet(session, events, max_chars=200)
        self.assertIn("first", packet["transcript"])
        self.assertIn("last", packet["transcript"])
        self.assertTrue(packet["packet_truncated"])

    def test_judge_is_blind_to_published_llm_labels(self) -> None:
        packet = {
            "session": {
                "session_id": "s", "repo_id": "r",
                "dataset_prompt_pushback_counts": {"requirement_change": 1},
                "session_success_dataset_label": "100",
                "user_persona_dataset_label": "Mind Changer",
                "observed_costs": {"human_rework_lines": 99},
            },
            "transcript": "T0 user_prompt: do it",
            "commits": [],
            "packet_truncated": False,
        }
        text = packet_as_text(packet)
        self.assertNotIn("requirement_change", text)
        self.assertNotIn("Mind Changer", text)
        self.assertNotIn("human_rework_lines", text)

    def test_behavior_episode_prefix_has_no_future_turns_or_outcome_metadata(self) -> None:
        packet = {
            "session": {
                "session_id": "s", "repo_id": "r", "agent": "a", "strategy": "x",
                "files_touched": ["future.py"], "total_committed": 10,
            },
            "transcript": "\n".join((
                "T0 user_prompt: first",
                "T1 assistant_response: doing first",
                "T2 user_prompt: later secret",
                "T3 assistant_response: doing later",
            )),
            "commits": ["commit future"],
            "packet_truncated": False,
        }
        views = behavior_episode_prefixes(packet)
        self.assertEqual(len(views), 2)
        self.assertEqual(views[0][0], 0)
        self.assertNotIn("later secret", views[0][1])
        self.assertNotIn("future.py", views[0][1])
        self.assertNotIn("commit future", views[0][1])
        self.assertEqual(views[0][2], {0, 1})

    def test_study1_validation_and_metrics(self) -> None:
        requirement_annotation = {
            "task_threads": [{
                "task_id": "task_1",
                "initial_instruction_turn": 0,
                "initial_requirements": ["export"],
                "initial_instruction_specificity": {
                    "score": 2,
                    "explicit_final_requirement_ids": ["R1"],
                    "missing_final_requirement_ids": ["R2"],
                    "rationale": "streaming omitted",
                },
                "requirement_events": [{
                    "turn": 2,
                    "first_explicit_turn": 2,
                    "first_user_requirement_turn": 2,
                    "proactive_question_turn": None,
                    "requirement_change": "new_requirement",
                    "requirement_id": "R2",
                    "requirement": "must stream",
                    "event_type": "environment_constraint_discovery",
                    "articulation_source": "user",
                    "requirement_basis": "project_grounded",
                    "basis_evidence_turns": [0, 1, 2],
                    "user_requirement_trigger": "execution_error",
                    "causal_link_strength": "strong",
                    "trigger_turns": [1],
                    "same_task": True,
                    "material": True,
                    "discovery_status": "discoverable_initially",
                    "earliest_discoverable_turn": 0,
                    "inferable_before_revelation": True,
                    "discovery_evidence_path": [
                        {"turn": 0, "source": "initial_instruction", "evidence": "large export"},
                        {"turn": 1, "source": "execution_error", "evidence": "memory failure"},
                    ],
                    "agent_recognition_turn": 2,
                    "correct_implementation_turn": 3,
                    "implementation_status": "satisfied",
                    "agent_response": "correctly_updated_after_new_evidence",
                    "regressed_requirement_ids": [],
                    "response_evidence_turns": [2, 3],
                    "evidence_turns": [0, 1, 2, 3],
                }],
                "final_requirements": [
                    {"requirement_id": "R1", "requirement": "export", "basis": "project_grounded",
                     "present_in_initial_instruction": True, "evidence_turns": [0]},
                    {"requirement_id": "R2", "requirement": "stream", "basis": "project_grounded",
                     "present_in_initial_instruction": False, "evidence_turns": [1, 2]},
                ],
                "literal_initial_completion_satisfies_final_requirements": False,
                "evidence_sufficient": True,
                "evolution_evidence_sufficient": True,
                "implementation_evidence_sufficient": True,
                "rationale": "memory failure",
            }],
            "confidence": 0.9,
        }
        validate_requirements_annotation(requirement_annotation, {0, 1, 2, 3})
        behavior = {
            "episode_in_scope": True,
            "instruction_turn": 0,
            "instruction_summary": "export",
            "project_reasoning_opportunity": True,
            "opportunity_reason": "large data",
            "classification_evidence_sufficient": True,
            "important_uncertainty_identified": True,
            "resolution_methods": ["repository_evidence"],
            "instruction_scope_preserved": True,
            "project_evidence_used": False,
            "unstated_material_requirement_or_downstream_impact_identified": False,
            "material_plan_scope_strategy_or_acceptance_affected": False,
            "proactive_before_explicit_correction": False,
            "rationale": "checked existing exporter",
            "requirement_novelty": "not_applicable",
            "novel_requirement": "", "material_change": "", "novelty_evidence_turns": [],
            "evidence": [{"turn": 1, "speaker_or_source": "assistant", "quote_or_paraphrase": "checked"}],
        }
        validate_behavior_annotation(behavior, 0, {0, 1})
        self.assertEqual(behavior["behavior_mode"], "instruction_scoped_sensemaking")
        summary = aggregate_study1(
            [{
                "session_id": "s1",
                "observed_costs": {
                    "human_rework_lines": 5, "committed_agent_code_share": 0.8,
                    "turn_count": 4, "tool_call_count": 2, "api_call_count": 2,
                    "total_tokens": 100, "duration_seconds": 30,
                },
                "turn_timestamps": {
                    "0": "2026-01-01T00:00:00+00:00",
                    "3": "2026-01-01T00:00:30+00:00",
                },
                "annotation": requirement_annotation,
            }], [{"annotation": behavior}]
        )
        self.assertEqual(summary["material_requirement_emergence_rate"]["estimate"], 1.0)
        self.assertEqual(
            summary["material_requirement_emergence_rate"]
            ["observation_or_feedback_triggered_event_rate"]["estimate"],
            1.0,
        )
        self.assertEqual(summary["literal_initial_instruction_satisfies_final_requirements_rate"]["estimate"], 0.0)
        self.assertEqual(summary["behavior_level_distribution"]["instruction_scoped_sensemaking"]["estimate"], 1.0)
        self.assertEqual(summary["initial_instruction_requirement_coverage"]["estimate"], 0.5)
        self.assertEqual(summary["post_initial_material_update_basis"]["project_grounded_rate"]["estimate"], 1.0)
        self.assertEqual(
            summary["cost_of_delayed_project_understanding"]
            ["evidence_to_correct_implementation_latency"]["turns"]["mean"],
            3.0,
        )

        aliased_requirements = deepcopy(requirement_annotation)
        aliased_event = aliased_requirements["task_threads"][0]["requirement_events"][0]
        aliased_event["user_requirement_trigger"] = "test_or_ci"
        aliased_event["discovery_evidence_path"][1]["source"] = "test_or_ci_feedback"
        normalize_study1_requirements(aliased_requirements)
        validate_requirements_annotation(aliased_requirements, {0, 1, 2, 3})
        self.assertEqual(aliased_event["user_requirement_trigger"], "test_or_ci_feedback")
        self.assertEqual(aliased_event["discovery_evidence_path"][1]["source"], "test_or_ci")

        invalid_requirements = deepcopy(requirement_annotation)
        invalid_requirements["task_threads"][0]["requirement_events"][0][
            "user_requirement_trigger"
        ] = "mystery_trigger"
        with self.assertRaisesRegex(
            ValueError, r"mystery_trigger.*allowed=.*test_or_ci_feedback"
        ):
            validate_requirements_annotation(invalid_requirements, {0, 1, 2, 3})

        non_user_event_annotation = deepcopy(requirement_annotation)
        non_user_event = non_user_event_annotation["task_threads"][0]["requirement_events"][0]
        non_user_event.update({
            "articulation_source": "agent",
            "user_requirement_trigger": "test_or_ci_feedback",
            "causal_link_strength": "strong",
            "trigger_turns": [1],
        })
        normalize_study1_requirements(non_user_event_annotation)
        validate_requirements_annotation(non_user_event_annotation, {0, 1, 2, 3})
        self.assertEqual(non_user_event["user_requirement_trigger"], "not_user_articulated")
        self.assertEqual(non_user_event["causal_link_strength"], "none")
        self.assertEqual(non_user_event["trigger_turns"], [])

        nonmaterial_annotation = deepcopy(requirement_annotation)
        nonmaterial_event = nonmaterial_annotation["task_threads"][0]["requirement_events"][0]
        nonmaterial_event.update({
            "material": False,
            "event_type": "process_only",
            "first_explicit_turn": None,
        })
        normalize_study1_requirements(nonmaterial_annotation)
        validate_requirements_annotation(nonmaterial_annotation, {0, 1, 2, 3})
        self.assertIsNone(nonmaterial_event["first_explicit_turn"])
        self.assertEqual(nonmaterial_event["implementation_status"], "not_applicable")

        spontaneous_annotation = deepcopy(requirement_annotation)
        spontaneous_event = spontaneous_annotation["task_threads"][0]["requirement_events"][0]
        spontaneous_event.update({
            "user_requirement_trigger": "spontaneous_user_revision",
            "causal_link_strength": "explicit",
            "trigger_turns": [],
        })
        normalize_study1_requirements(spontaneous_annotation)
        validate_requirements_annotation(spontaneous_annotation, {0, 1, 2, 3})
        self.assertEqual(spontaneous_event["causal_link_strength"], "explicit")

        aliased_behavior = deepcopy(behavior)
        aliased_behavior["resolution_methods"] = ["repository_inspection"]
        normalize_study1_behavior(aliased_behavior)
        validate_behavior_annotation(aliased_behavior, 0, {0, 1})
        self.assertEqual(aliased_behavior["resolution_methods"], ["repository_evidence"])

    def test_study1_level3_is_derived_from_atomic_fields(self) -> None:
        value = {
            "episode_in_scope": True,
            "classification_evidence_sufficient": True,
            "important_uncertainty_identified": False,
            "resolution_methods": [],
            "instruction_scope_preserved": False,
            "project_evidence_used": True,
            "unstated_material_requirement_or_downstream_impact_identified": True,
            "material_plan_scope_strategy_or_acceptance_affected": True,
            "requirement_novelty": "new_material_requirement",
            "novel_requirement": "bounded memory", "material_change": "stream instead of buffering",
            "novelty_evidence_turns": [1],
        }
        derive_behavior_mode(value)
        self.assertEqual(value["behavior_mode"], "project_level_requirement_discovery")

    def test_study2_validation_and_metrics(self) -> None:
        annotation = {
            "task_threads": [{
                "task_id": "task_1",
                "surface_instruction": "make it faster",
                "surface_instruction_turn": 0,
                "user_belief_identifiable": True,
                "user_belief": "optimizing the hot loop will fix startup latency",
                "belief_evidence": [{
                    "turn": 0,
                    "source": "surface_instruction",
                    "evidence": "user asks to optimize the loop for startup",
                }],
                "actual_situation_identifiable": True,
                "actual_project_situation": "dependency initialization causes startup latency",
                "actual_situation_evidence": [{
                    "turn": 2,
                    "source": "observed_output",
                    "evidence": "profile attributes startup time to dependency initialization",
                }],
                "material_instruction_reality_mismatch": True,
                "mismatch_types": ["incorrect_problem_diagnosis"],
                "mismatch_discovery": {
                    "initial_state_discoverability": "discoverable",
                    "earliest_mismatch_evidence_turn": 0,
                    "first_user_mismatch_explanation_turn": 3,
                    "mismatch_evidence_path": [{
                        "turn": 0,
                        "source": "surface_instruction",
                        "evidence": "the requested mechanism is explicit",
                    }, {
                        "turn": 2,
                        "source": "observed_output",
                        "evidence": "profile reveals the actual bottleneck",
                    }],
                },
                "gap_driver": "prior_experience_or_analogy",
                "gap_driver_evidence_strength": "explicit",
                "belief_basis_scope": "partial_observation",
                "driver_evidence": [{"turn": 0, "evidence": "user cites a similar prior optimization"}],
                "literal_counterfactual": {
                    "surface_instruction_satisfied": True,
                    "actual_situation_addressed": False,
                    "failure_caused_by_mismatch": True,
                },
                "agent_gap_response": {
                    "classification_evidence_sufficient": True,
                    "considered_user_belief_or_goal": True,
                    "identified_instruction_uncertainty": False,
                    "asked_targeted_clarification": False,
                    "identified_instruction_reality_gap": True,
                    "challenged_or_deviated_from_instruction": True,
                    "followed_surface_instruction": False,
                    "proactive_before_user_explained_mismatch": True,
                    "mental_state_consideration_turn": 1,
                    "reality_gap_detection_turn": 2,
                    "clarification_turn": None,
                    "resistance_turn": 2,
                    "surface_action_commitment_turn": None,
                    "actual_situation_addressed_turn": 3,
                    "detection_methods": ["observed_output", "causal_reasoning"],
                    "observed_resolution_status": "resolved",
                    "evidence_turns": [1, 2, 3],
                },
                "rationale": "the requested optimization targets the wrong cause",
            }],
            "confidence": 0.8,
        }
        validate_intent_annotation(annotation, {0, 1, 2, 3}, {0, 3})
        summary = aggregate_study2([{
            "session_id": "s1",
            "turn_timestamps": {
                "0": "2026-01-01T00:00:00Z", "1": "2026-01-01T00:00:01Z",
                "2": "2026-01-01T00:00:02Z", "3": "2026-01-01T00:00:03Z",
            },
            "observed_costs": {"turn_count": 4},
            "annotation": annotation,
        }])
        self.assertEqual(summary["material_instruction_reality_mismatch_rate"]["estimate"], 1.0)
        self.assertEqual(summary["literal_compliance_but_reality_failure_rate"]["estimate"], 1.0)
        response = summary["agent_gap_detection_and_response"]
        self.assertEqual(response["user_mental_state_consideration_rate"]["estimate"], 1.0)
        self.assertEqual(
            response["response_pattern_rates"]["detects_reality_gap_and_resists"]["estimate"], 1.0
        )
        self.assertEqual(
            response["evidence_to_reality_gap_detection_latency"]["turns"]["mean"], 2.0
        )
        self.assertEqual(
            summary["mismatch_discoverability_and_route"]["initially_discoverable_rate"]["estimate"],
            1.0,
        )
        self.assertEqual(
            summary["observed_resolution_by_agent_response"]
            ["detects_reality_gap_and_resists"]["resolved_rate"]["estimate"],
            1.0,
        )
        self.assertEqual(summary["gap_driver"]["distribution"]["prior_experience_or_analogy"], 1)
        self.assertEqual(summary["gap_driver"]["partial_observation_belief_rate"]["estimate"], 1.0)

        faithful_annotation = deepcopy(annotation)
        faithful_response = faithful_annotation["task_threads"][0]["agent_gap_response"]
        faithful_response.update({
            "classification_evidence_sufficient": True,
            "considered_user_belief_or_goal": False,
            "identified_instruction_uncertainty": False,
            "asked_targeted_clarification": False,
            "identified_instruction_reality_gap": False,
            "challenged_or_deviated_from_instruction": False,
            "followed_surface_instruction": True,
            "proactive_before_user_explained_mismatch": False,
            "mental_state_consideration_turn": None,
            "reality_gap_detection_turn": None,
            "clarification_turn": None,
            "resistance_turn": None,
            "surface_action_commitment_turn": 1,
            "actual_situation_addressed_turn": None,
            "detection_methods": [],
            "observed_resolution_status": "unresolved",
            "evidence_turns": [1],
        })
        validate_intent_annotation(faithful_annotation, {0, 1, 2, 3}, {0, 3})
        two_group_summary = aggregate_study2([{
            "session_id": "early",
            "observed_costs": {"turn_count": 4},
            "annotation": annotation,
        }, {
            "session_id": "faithful",
            "observed_costs": {"turn_count": 10},
            "annotation": faithful_annotation,
        }])
        cost = two_group_summary["cost_of_faithful_execution_under_mismatch"]
        self.assertEqual(cost["faithful_execution_session_count"], 1)
        self.assertEqual(cost["early_handling_session_count"], 1)
        self.assertEqual(
            cost["session_level_descriptive_comparisons"]["turn_count"]
            ["mean_difference_faithful_minus_early_handling"],
            6.0,
        )

        aliased_study2 = deepcopy(annotation)
        aliased_thread = aliased_study2["task_threads"][0]
        aliased_thread["gap_driver"] = "experience"
        aliased_thread["gap_driver_evidence_strength"] = "strong"
        aliased_thread["belief_evidence"][0]["source"] = "user_experience"
        aliased_thread["actual_situation_evidence"][0]["source"] = "output"
        aliased_thread["mismatch_discovery"]["mismatch_evidence_path"][1]["source"] = "output"
        aliased_thread["agent_gap_response"]["detection_methods"] = ["reasoning"]
        normalize_study2_annotation(aliased_study2)
        validate_intent_annotation(aliased_study2, {0, 1, 2, 3}, {0, 3})
        self.assertEqual(aliased_thread["gap_driver"], "prior_experience_or_analogy")
        self.assertEqual(aliased_thread["gap_driver_evidence_strength"], "strong_inference")
        self.assertEqual(aliased_thread["actual_situation_evidence"][0]["source"], "observed_output")

        no_mismatch_annotation = deepcopy(annotation)
        no_mismatch_thread = no_mismatch_annotation["task_threads"][0]
        no_mismatch_thread["material_instruction_reality_mismatch"] = False
        no_mismatch_thread["mismatch_discovery"] = None
        no_mismatch_thread["literal_counterfactual"] = None
        no_mismatch_thread["agent_gap_response"] = None
        normalize_study2_annotation(no_mismatch_annotation)
        validate_intent_annotation(no_mismatch_annotation, {0, 1, 2, 3}, {0, 3})
        self.assertEqual(no_mismatch_thread["mismatch_types"], ["no_material_mismatch"])
        self.assertEqual(no_mismatch_thread["gap_driver"], "no_material_mismatch")
        self.assertFalse(
            no_mismatch_thread["agent_gap_response"]["classification_evidence_sufficient"]
        )
        self.assertEqual(
            no_mismatch_thread["mismatch_discovery"]["mismatch_evidence_path"], []
        )

        inferred_response_evidence = deepcopy(annotation)
        inferred_response = inferred_response_evidence["task_threads"][0]["agent_gap_response"]
        inferred_response["evidence_turns"] = []
        inferred_response["detection_methods"] = []
        normalize_study2_annotation(inferred_response_evidence)
        validate_intent_annotation(inferred_response_evidence, {0, 1, 2, 3}, {0, 3})
        self.assertEqual(inferred_response["evidence_turns"], [1, 2])

        followed_then_detected = deepcopy(annotation)
        followed_response = followed_then_detected["task_threads"][0]["agent_gap_response"]
        followed_response["surface_action_commitment_turn"] = 1
        normalize_study2_annotation(followed_then_detected)
        validate_intent_annotation(followed_then_detected, {0, 1, 2, 3}, {0, 3})
        self.assertTrue(followed_response["challenged_or_deviated_from_instruction"])
        self.assertEqual(followed_response["resistance_turn"], 2)
        self.assertTrue(followed_response["followed_surface_instruction"])
        self.assertFalse(followed_response["proactive_before_user_explained_mismatch"])
        self.assertEqual(followed_response["response_pattern"], "follows_surface_instruction")

    def test_validation_failure_preserves_both_invalid_annotations(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.outputs = iter([{"attempt": 1}, {"attempt": 2}])

            def complete_json(self, system: str, prompt: str) -> tuple[dict, dict]:
                return next(self.outputs), {}

        def reject(value: dict) -> None:
            raise ValueError(f"bad attempt={value['attempt']}; allowed=['valid']")

        with self.assertRaises(AnnotationValidationFailure) as caught:
            _complete_validated_json(FakeClient(), "system", "prompt", lambda value: None, reject)
        record = _failure_record(caught.exception, session_id="s")
        self.assertEqual(record["initial_invalid_annotation"], {"attempt": 1})
        self.assertEqual(record["repaired_invalid_annotation"], {"attempt": 2})
        self.assertIn("allowed=['valid']", record["repair_error"])

    def test_study2_response_pattern_precedence(self) -> None:
        thread = {
            "material_instruction_reality_mismatch": True,
            "agent_gap_response": {
                "classification_evidence_sufficient": True,
                "considered_user_belief_or_goal": True,
                "identified_instruction_reality_gap": False,
                "challenged_or_deviated_from_instruction": False,
                "identified_instruction_uncertainty": True,
                "asked_targeted_clarification": True,
                "followed_surface_instruction": True,
                "surface_action_commitment_turn": 1,
                "clarification_turn": 2,
                "resistance_turn": None,
            },
        }
        derive_agent_response_pattern(thread)
        self.assertEqual(
            thread["agent_gap_response"]["response_pattern"],
            "follows_surface_instruction",
        )

        thread["agent_gap_response"].update({
            "followed_surface_instruction": False,
            "surface_action_commitment_turn": 3,
        })
        derive_agent_response_pattern(thread)
        self.assertEqual(
            thread["agent_gap_response"]["response_pattern"],
            "clarifies_instruction_uncertainty",
        )

        thread["agent_gap_response"].update({
            "identified_instruction_uncertainty": False,
            "asked_targeted_clarification": False,
            "identified_instruction_reality_gap": True,
            "challenged_or_deviated_from_instruction": True,
            "resistance_turn": 2,
        })
        derive_agent_response_pattern(thread)
        self.assertEqual(
            thread["agent_gap_response"]["response_pattern"],
            "detects_reality_gap_and_resists",
        )


if __name__ == "__main__":
    unittest.main()
