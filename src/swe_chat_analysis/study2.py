from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import isfinite
import re
from statistics import mean, median
from typing import Any


STUDY2_RUBRIC_VERSION = "user_belief_reality_gap_v8"

MISMATCH_TYPES = {
    "incorrect_problem_diagnosis", "requested_means_conflicts_with_goal",
    "omitted_material_requirement", "infeasible_or_incompatible_instruction",
    "wrong_abstraction_level", "other_material_mismatch", "no_material_mismatch",
}
BELIEF_EVIDENCE_SOURCES = {
    "surface_instruction", "later_user_explanation", "user_preference_statement",
    "user_experience_statement", "user_knowledge_statement", "user_assumption_statement",
    "agent_question_user_answer", "other_user_statement",
}
ACTUAL_SITUATION_EVIDENCE_SOURCES = {
    "user_correction", "user_rejection", "user_confirmation", "project_invariant",
    "documentation", "test_or_ci", "execution_error", "observed_output", "review",
}
GAP_DRIVERS = {
    "personal_preference_or_value", "prior_experience_or_analogy",
    "domain_or_technical_knowledge", "project_specific_knowledge",
    "current_observation_or_feedback", "external_information_or_advice",
    "assumption_without_stated_basis", "mixed", "unclear", "no_material_mismatch",
}
DRIVER_EVIDENCE_STRENGTHS = {"explicit", "strong_inference", "weak_inference", "insufficient"}
AGENT_RESPONSE_PATTERNS = {
    "follows_surface_instruction", "clarifies_instruction_uncertainty",
    "detects_reality_gap_and_resists", "mixed_or_other", "unclear",
    "no_material_mismatch",
}
MISMATCH_DISCOVERY_SOURCES = ACTUAL_SITUATION_EVIDENCE_SOURCES | {
    "surface_instruction", "later_user_explanation", "agent_inference",
}
AGENT_DETECTION_METHODS = {
    "targeted_user_question", "repository_inspection", "documentation_or_interface",
    "test_or_ci", "execution_or_error", "observed_output", "prior_context_or_requirement",
    "alternative_comparison", "causal_reasoning", "other",
}
RESOLUTION_STATUSES = {"resolved", "partial", "unresolved", "unknown"}
INITIAL_DISCOVERABILITY_STATUSES = {"discoverable", "not_discoverable", "unclear", "not_applicable"}
BELIEF_BASIS_SCOPES = {
    "partial_observation", "broadly_grounded", "non_observational", "unclear", "not_applicable",
}


SYSTEM_PROMPT = r"""You are neutrally annotating a possible mismatch between a user's surface
instruction and the evidence-supported actual project situation, including the belief that appears
to motivate the instruction and how the agent responds during user-agent interaction. Mental-state
claims are inferences, not direct observations. The hypotheses may be false; no mismatch, an
unidentifiable belief, and insufficient evidence are valid outcomes.

Unit:
- Split into task threads. A thread is one continuing project objective; an independent later task
  is not evidence of earlier intent.
- Keep a later correction, rejection, constraint, or change of means in the same thread when it
  refines how the same underlying objective must be achieved. Do not hide an initial mismatch by
  splitting each corrective user message into a new task thread.
- surface_instruction is the first substantive request, interpreted literally with reasonable defaults.

User belief and its source:
- user_belief is the proposition about the problem, desired outcome, causal mechanism, or suitable
  solution that appears to motivate the surface instruction. Do not equate an instruction with a
  belief when several beliefs could motivate it; then set user_belief_identifiable=false.
- gap_driver asks what best explains the formation of that belief: personal_preference_or_value;
  prior_experience_or_analogy; domain_or_technical_knowledge; project_specific_knowledge;
  current_observation_or_feedback; external_information_or_advice; or
  assumption_without_stated_basis. Use mixed when multiple evidenced sources are inseparable and
  unclear when the source cannot be inferred. It is the source of the belief motivating the
  instruction, not the source of the actual project condition or merely the point when a mismatch
  became visible.
- Preference is a value or desired workflow, not deficient knowledge. Experience requires evidence
  of prior exposure or analogy. Knowledge background requires explicit or strong evidence of general
  domain/technical knowledge; do not infer it merely from fluency or vocabulary. Project-specific
  knowledge concerns this repository, users, history, or workflow. Current observation/feedback is
  evidence encountered in this session. External information/advice includes docs, standards,
  stakeholders, reviewers, or other people. assumption_without_stated_basis means the instruction
  rests on an apparent assumption but the trace supplies no source for it.
- Record whether the source evidence is explicit, a strong inference, a weak inference, or
  insufficient. Weak/insufficient evidence must not be written as fact. Insufficient normally uses
  gap_driver=unclear; use assumption_without_stated_basis only when the instruction evidences an
  assumption but the trace supplies no basis for it. Copy supporting turns into belief_evidence and
  driver_evidence.
- belief_basis_scope asks whether the belief is based on a partial_observation (a local symptom,
  single output, subset of code, stale state, or selective evidence that omits materially relevant
  contrary context), is broadly_grounded in the relevant available evidence, is non_observational
  such as a preference/value, or is unclear. Do not label partial merely because the belief is wrong;
  require evidence that the information basis was materially incomplete.

Actual situation:
- actual_project_situation is the evidence-supported target and project reality against which the
  instruction is evaluated. It may include a later-confirmed user goal or preference and objective
  facts/constraints from repository invariants, docs/interfaces, tests/CI, execution errors,
  observed output, or review. User statements can establish the user's goal or preference, but a
  factual project claim normally needs project evidence. An agent proposal, implementation, or
  commit alone cannot establish it.
- If plausible actual situations remain indistinguishable, set actual_situation_identifiable=false
  and do not assert a mismatch.

A material instruction-reality mismatch exists when following the surface instruction with
reasonable defaults would (a) materially conflict with the actual project situation, (b) solve the
wrong problem or use a means that does not achieve the evidenced underlying goal, or (c) omit a
concrete acceptance, scope, source-of-truth, compatibility, safety, or functional condition whose
absence would cause rejection, non-trivial revision, or an inability to establish success. The
actual situation includes a stable latent requirement later revealed by user correction or
rejection; it need not be an objective repository invariant. The literal action may be implementable
and an actual failure need not already have occurred. Concrete project or later-interaction evidence
of goal divergence is sufficient. An omitted requirement counts even when it was not stated in the
first instruction, provided later evidence shows that a competent literal implementation with
reasonable defaults would still choose the wrong behavior, scope, architecture, or source of truth.

Use this decision test:
1. Construct the competent literal result from the first instruction and then-existing project state.
2. Construct the evidence-supported result actually needed for the same objective, using later user
   corrections/rejections as evidence when they reveal a stable acceptance criterion.
3. Mark mismatch when the two differ in a consequential way requiring more than cosmetic or routine
   adjustment. A user correction followed by non-trivial rework is strong evidence, but the rework
   must address an instruction/goal gap rather than an agent implementation mistake.

Examples: choosing an automated commit author when the user later establishes that the code-change
author is the required identity is a mismatch; implementing a requested component while omitting a
later-confirmed integration or behavior criterion is a mismatch. In contrast, a request to evaluate
whether a library fits is not mismatched merely because a competent evaluation concludes that it
does not fit: a negative conclusion is an allowed result of the requested evaluation.
Mismatch types are: incorrect_problem_diagnosis; requested_means_conflicts_with_goal;
omitted_material_requirement; infeasible_or_incompatible_instruction; wrong_abstraction_level;
other_material_mismatch; or no_material_mismatch. Do not manufacture a mismatch from a harmless
implementation choice, generic underspecification that reasonable defaults resolve, or hindsight
unavailable anywhere in the supplied session. Do not aim for a target mismatch prevalence.

Mismatch discoverability:
- initial_state_discoverability=discoverable only when a competent autonomous agent could have found
  the mismatch from the initial instruction and then-existing project state, including evidence it
  could reasonably inspect. Use not_discoverable when the decisive fact arose later, unclear when the
  supplied packet cannot establish either, and not_applicable when there is no identifiable mismatch.
  Do not require that the user had already stated the correction.
- earliest_mismatch_evidence_turn is the earliest supplied T<number> containing a clue that could
  support the mismatch. It may be later than the initial instruction even when the underlying
  repository fact existed initially. Keep the separate initial-state boolean for that distinction.
- first_user_mismatch_explanation_turn is the first user turn that explicitly explains/corrects the
  relevant mismatch; null if the user never does. A rejection without explaining the mismatch is not
  enough.
- mismatch_evidence_path is a chronological chain from earliest clue to confirmation, using sources:
  surface_instruction, later_user_explanation, user_correction, user_rejection, user_confirmation,
  project_invariant, documentation, test_or_ci, execution_error, observed_output, review, or
  agent_inference.

Literal counterfactual:
- Imagine a competent agent has only the surface instruction and initial project state and completes
  its literal request with reasonable defaults, without later messages/failures.
- Separate obeying the words from addressing the actual situation. failure_caused_by_mismatch=true
  only when the instruction-reality mismatch, rather than agent incompetence, causes failure.

Agent consideration and response, evaluated over the interaction:
- considered_user_belief_or_goal=true only when the agent explicitly connects the surface request to
  a hypothesized latent goal, preference, assumption, knowledge state, or problem model, or directly
  asks about one of them. Repository inspection, testing, causal debugging, alternative comparison,
  restatement, politeness, and implementation-choice questions do not count by themselves. The
  evidence turn must show the mental-state/goal connection, not merely competent project reasoning.
- identified_instruction_uncertainty means the agent explicitly identifies a material ambiguity in
  the user's intended outcome, premise, or acceptance criterion. asked_targeted_clarification
  additionally requires a direct question whose answer would distinguish those interpretations.
  Questions only about implementation preferences, permissions, or routine details do not count.
- identified_instruction_reality_gap means the agent recognizes that the surface instruction rests
  on a mistaken/incomplete assumption or conflicts with project evidence, and explicitly connects
  that evidence to why literal compliance risks the user's actual goal. Merely finding the
  instruction vague, discovering a technical fact, silently changing implementation, or repairing
  after failure does not count. Qualifying detection also counts as user-belief consideration.
- surface_action_commitment_turn is the first turn where the agent commits to the consequential
  surface course: editing/implementing it, executing an externally consequential action, or clearly
  endorsing it as the solution. Reading code, inspecting the repository, consulting documentation,
  running diagnostic tests, comparing alternatives, and planning in order to validate the premise
  are pre-action due diligence and do not count as commitment. For a pure research/evaluation task,
  performing the requested evaluation is the action, but reporting a supported negative conclusion
  is not resistance because the instruction did not require adoption.
- challenged_or_deviated_from_instruction means the agent explains the evidenced conflict and
  refuses, pauses, challenges, or materially redirects the requested action because of it. It is an
  early detect-and-resist response only when resistance_turn precedes surface_action_commitment_turn,
  or when no surface commitment occurs. Unsupported disobedience does not count.
- followed_surface_instruction means the consequential surface action was committed before a
  qualifying clarification or gap-aware resistance. Later detection or repair does not erase it.
- proactive_before_user_explained_mismatch=true only when the agent considers or detects the issue
  before both surface_action_commitment_turn and the first user correction, rejection, or explicit
  explanation of the mismatch.
- mental_state_consideration_turn is the first turn supporting considered_user_belief_or_goal.
  reality_gap_detection_turn is the first turn supporting identified_instruction_reality_gap.
  clarification_turn, resistance_turn, and surface_action_commitment_turn are the first turns
  supporting those actions. Use null when the corresponding event is absent.
  actual_situation_addressed_turn is the first supplied turn showing the actual situation was
  substantively addressed, not merely discussed.
- detection_methods records how the agent considered or detected the issue: targeted_user_question,
  repository_inspection, documentation_or_interface, test_or_ci, execution_or_error,
  observed_output, prior_context_or_requirement, alternative_comparison, causal_reasoning, or other.
- observed_resolution_status describes the thread's observed final state: resolved, partial,
  unresolved, or unknown. Commit metadata may corroborate but cannot by itself prove resolution.

The pipeline derives a mutually exclusive initial response pattern for material mismatches from event
order, not from whether the agent did any useful work:
1. detects_reality_gap_and_resists: explicitly identified the gap and challenged/deviated before the
   first consequential surface-action commitment, or without ever making that commitment.
2. clarifies_instruction_uncertainty: asked a targeted material clarification before the first
   consequential surface-action commitment, with no earlier qualifying resistance.
3. follows_surface_instruction: committed to the consequential surface action before either form of
   early handling; later clarification, detection, resistance, or repair does not change this pattern.
4. mixed_or_other: sufficient evidence exists but none of the three patterns fits cleanly.
Use unclear when response evidence is absent/truncated or genuinely indeterminate, and
no_material_mismatch when there is no mismatch. Do not output response_pattern yourself.

Evidence turns must be copied from T<number> labels. Commit metadata only corroborates implementation.
Exact enum contract (copy these values exactly):
- belief_evidence[].source: surface_instruction, later_user_explanation,
  user_preference_statement, user_experience_statement, user_knowledge_statement,
  user_assumption_statement, agent_question_user_answer, other_user_statement.
- actual_situation_evidence[].source: user_correction, user_rejection, user_confirmation,
  project_invariant, documentation, test_or_ci, execution_error, observed_output, review.
- mismatch_types[]: incorrect_problem_diagnosis, requested_means_conflicts_with_goal,
  omitted_material_requirement, infeasible_or_incompatible_instruction, wrong_abstraction_level,
  other_material_mismatch, no_material_mismatch.
- gap_driver: personal_preference_or_value, prior_experience_or_analogy,
  domain_or_technical_knowledge, project_specific_knowledge, current_observation_or_feedback,
  external_information_or_advice, assumption_without_stated_basis, mixed, unclear,
  no_material_mismatch.
- gap_driver_evidence_strength: explicit, strong_inference, weak_inference, insufficient.
- belief_basis_scope: partial_observation, broadly_grounded, non_observational, unclear,
  not_applicable.
- mismatch_discovery.initial_state_discoverability: discoverable, not_discoverable, unclear,
  not_applicable.
- mismatch_evidence_path[].source: surface_instruction, later_user_explanation, user_correction,
  user_rejection, user_confirmation, project_invariant, documentation, test_or_ci, execution_error,
  observed_output, review, agent_inference.
- detection_methods[]: targeted_user_question, repository_inspection,
  documentation_or_interface, test_or_ci, execution_or_error, observed_output,
  prior_context_or_requirement, alternative_comparison, causal_reasoning, other.
- observed_resolution_status: resolved, partial, unresolved, unknown.
Return exactly one JSON object:
{
  "task_threads": [{
    "task_id": "task_1",
    "surface_instruction": "string",
    "surface_instruction_turn": 0,
    "user_belief_identifiable": true,
    "user_belief": "the requested local optimization will fix startup latency",
    "belief_evidence": [{"turn": 0, "source": "surface_instruction", "evidence": "string"}],
    "actual_situation_identifiable": true,
    "actual_project_situation": "startup latency is caused by dependency initialization",
    "actual_situation_evidence": [{"turn": 2, "source": "execution_error", "evidence": "string"}],
    "material_instruction_reality_mismatch": true,
    "mismatch_types": ["incorrect_problem_diagnosis"],
    "mismatch_discovery": {
      "initial_state_discoverability": "discoverable",
      "earliest_mismatch_evidence_turn": 0,
      "first_user_mismatch_explanation_turn": 3,
      "mismatch_evidence_path": [
        {"turn": 0, "source": "surface_instruction", "evidence": "string"},
        {"turn": 2, "source": "observed_output", "evidence": "string"}
      ]
    },
    "gap_driver": "prior_experience_or_analogy",
    "gap_driver_evidence_strength": "explicit",
    "belief_basis_scope": "partial_observation",
    "driver_evidence": [{"turn": 3, "evidence": "string"}],
    "literal_counterfactual": {
      "surface_instruction_satisfied": true,
      "actual_situation_addressed": false,
      "failure_caused_by_mismatch": true
    },
    "agent_gap_response": {
      "classification_evidence_sufficient": true,
      "considered_user_belief_or_goal": true,
      "identified_instruction_uncertainty": false,
      "asked_targeted_clarification": false,
      "identified_instruction_reality_gap": true,
      "challenged_or_deviated_from_instruction": true,
      "followed_surface_instruction": false,
      "proactive_before_user_explained_mismatch": true,
      "mental_state_consideration_turn": 1,
      "reality_gap_detection_turn": 2,
      "clarification_turn": null,
      "resistance_turn": 2,
      "surface_action_commitment_turn": null,
      "actual_situation_addressed_turn": 4,
      "detection_methods": ["observed_output", "causal_reasoning"],
      "observed_resolution_status": "resolved",
      "evidence_turns": [1, 2]
    },
    "rationale": "string"
  }],
  "confidence": 0.0
}
When actual_situation_identifiable=false: empty actual_project_situation/evidence and mismatch_types;
material_instruction_reality_mismatch=false; counterfactual flags false; gap_driver=unclear and
gap_driver_evidence_strength=insufficient; use not_applicable/null/empty mismatch_discovery fields and
observed_resolution_status=unknown. When user_belief_identifiable=false, leave user_belief and
belief_evidence empty and use gap_driver=unclear unless there is no material mismatch. For no mismatch,
use mismatch_types=["no_material_mismatch"], gap_driver=no_material_mismatch, evidence strength
insufficient, belief_basis_scope=not_applicable, empty driver_evidence, not_applicable/null/empty
mismatch-discovery and agent fields, and
observed_resolution_status=unknown. Use JSON primitives and no markdown."""


def user_prompt(packet_text: str) -> str:
    return ("Annotate the user's apparent belief and its source, the instruction–reality mismatch, "
            "and whether the agent followed, clarified, or resisted the instruction.\n\n" + packet_text)


def _normalized_enum(value: Any, allowed: set[str], aliases: dict[str, str] | None = None) -> Any:
    if not isinstance(value, str):
        return value
    token = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    token = (aliases or {}).get(token, token)
    return token if token in allowed else value


def _invalid_enum(field: str, value: Any, allowed: set[str]) -> ValueError:
    return ValueError(f"invalid {field}={value!r}; allowed={sorted(allowed)}")


def _normalize_no_mismatch_fields(thread: dict[str, Any], gap_driver: str) -> None:
    thread["material_instruction_reality_mismatch"] = False
    thread["gap_driver"] = gap_driver
    thread["gap_driver_evidence_strength"] = "insufficient"
    thread["belief_basis_scope"] = "not_applicable"
    thread["driver_evidence"] = []
    if gap_driver == "no_material_mismatch":
        thread["mismatch_types"] = ["no_material_mismatch"]
    else:
        thread["mismatch_types"] = []
    discovery = thread.get("mismatch_discovery")
    if not isinstance(discovery, dict):
        discovery = {}
        thread["mismatch_discovery"] = discovery
    discovery.update({
        "initial_state_discoverability": "not_applicable",
        "earliest_mismatch_evidence_turn": None,
        "first_user_mismatch_explanation_turn": None,
        "mismatch_evidence_path": [],
    })
    counterfactual = thread.get("literal_counterfactual")
    if not isinstance(counterfactual, dict):
        counterfactual = {}
        thread["literal_counterfactual"] = counterfactual
    counterfactual.update({
        "surface_instruction_satisfied": False,
        "actual_situation_addressed": False,
        "failure_caused_by_mismatch": False,
    })
    response = thread.get("agent_gap_response")
    if not isinstance(response, dict):
        response = {}
        thread["agent_gap_response"] = response
    for field in (
        "classification_evidence_sufficient", "considered_user_belief_or_goal",
        "identified_instruction_uncertainty", "asked_targeted_clarification",
        "identified_instruction_reality_gap", "challenged_or_deviated_from_instruction",
        "followed_surface_instruction", "proactive_before_user_explained_mismatch",
    ):
        response[field] = False
    for field in (
        "mental_state_consideration_turn", "reality_gap_detection_turn",
        "clarification_turn", "resistance_turn", "surface_action_commitment_turn",
        "actual_situation_addressed_turn",
    ):
        response[field] = None
    response["detection_methods"] = []
    response["observed_resolution_status"] = "unknown"
    response["evidence_turns"] = []


def normalize_annotation(value: dict[str, Any]) -> None:
    for thread in value.get("task_threads", []):
        for field in ("user_belief_identifiable", "actual_situation_identifiable",
                      "material_instruction_reality_mismatch"):
            if thread.get(field) is None:
                thread[field] = False
        for field in ("belief_evidence", "actual_situation_evidence", "mismatch_types",
                      "driver_evidence"):
            if thread.get(field) is None:
                thread[field] = []
        for item in thread.get("belief_evidence", []):
            item["source"] = _normalized_enum(item.get("source"), BELIEF_EVIDENCE_SOURCES, {
                "user_explanation": "later_user_explanation",
                "user_preference": "user_preference_statement",
                "preference": "user_preference_statement",
                "user_experience": "user_experience_statement",
                "experience": "user_experience_statement",
                "user_knowledge": "user_knowledge_statement",
                "domain_knowledge": "user_knowledge_statement",
                "knowledge_background": "user_knowledge_statement",
                "user_assumption": "user_assumption_statement",
                "assumption": "user_assumption_statement",
                "user_answer": "agent_question_user_answer",
                "targeted_user_answer": "agent_question_user_answer",
                "user_correction": "other_user_statement",
                "user_rejection": "other_user_statement",
                "user_confirmation": "other_user_statement",
            })
        for item in thread.get("actual_situation_evidence", []):
            item["source"] = _normalized_enum(item.get("source"), ACTUAL_SITUATION_EVIDENCE_SOURCES, {
                "test": "test_or_ci", "ci": "test_or_ci", "test_ci": "test_or_ci",
                "test_or_ci_feedback": "test_or_ci", "error": "execution_error",
                "output": "observed_output", "observed_output_feedback": "observed_output",
                "repository": "project_invariant", "repo": "project_invariant",
                "interface": "documentation", "docs": "documentation",
                "user_acceptance": "user_confirmation",
                "user_preference_statement": "user_correction",
                "later_user_explanation": "user_correction",
            })
        if isinstance(thread.get("mismatch_types"), list):
            mismatch_aliases = {
                "wrong_problem_diagnosis": "incorrect_problem_diagnosis",
                "proxy_action_vs_real_goal": "requested_means_conflicts_with_goal",
                "implicit_acceptance_criterion": "omitted_material_requirement",
                "implicit_project_constraint": "omitted_material_requirement",
                "surface_intent_conflict": "requested_means_conflicts_with_goal",
                "incompatible_instruction": "infeasible_or_incompatible_instruction",
                "no_material_gap": "no_material_mismatch", "no_mismatch": "no_material_mismatch",
            }
            thread["mismatch_types"] = list(dict.fromkeys(
                _normalized_enum(item, MISMATCH_TYPES, mismatch_aliases)
                for item in thread["mismatch_types"]
            ))
        thread["gap_driver"] = _normalized_enum(thread.get("gap_driver"), GAP_DRIVERS, {
            "preference": "personal_preference_or_value",
            "personal_preference": "personal_preference_or_value",
            "experience": "prior_experience_or_analogy",
            "prior_experience": "prior_experience_or_analogy",
            "knowledge_background": "domain_or_technical_knowledge",
            "domain_knowledge": "domain_or_technical_knowledge",
            "technical_knowledge": "domain_or_technical_knowledge",
            "project_knowledge": "project_specific_knowledge",
            "observation": "current_observation_or_feedback",
            "current_observation": "current_observation_or_feedback",
            "external_advice": "external_information_or_advice",
            "unsupported_assumption": "assumption_without_stated_basis",
            "no_material_gap": "no_material_mismatch",
        })
        thread["gap_driver_evidence_strength"] = _normalized_enum(
            thread.get("gap_driver_evidence_strength"), DRIVER_EVIDENCE_STRENGTHS,
            {"strong": "strong_inference", "weak": "weak_inference", "none": "insufficient"},
        )
        thread["belief_basis_scope"] = _normalized_enum(
            thread.get("belief_basis_scope"), BELIEF_BASIS_SCOPES,
            {"partial": "partial_observation", "broad": "broadly_grounded",
             "well_grounded": "broadly_grounded", "preference": "non_observational",
             "non_observation": "non_observational", "not_relevant": "not_applicable"},
        )
        discovery = thread.get("mismatch_discovery")
        if isinstance(discovery, dict):
            if discovery.get("initial_state_discoverability") is None:
                discovery["initial_state_discoverability"] = "unclear"
            if isinstance(discovery.get("initial_state_discoverability"), bool):
                discovery["initial_state_discoverability"] = (
                    "discoverable" if discovery["initial_state_discoverability"] else "not_discoverable"
                )
            discovery["initial_state_discoverability"] = _normalized_enum(
                discovery.get("initial_state_discoverability"), INITIAL_DISCOVERABILITY_STATUSES,
                {"initially_discoverable": "discoverable", "not_initially_discoverable": "not_discoverable",
                 "unknown": "unclear", "none": "not_applicable"},
            )
            if discovery.get("mismatch_evidence_path") is None:
                discovery["mismatch_evidence_path"] = []
            for item in discovery.get("mismatch_evidence_path", []):
                item["source"] = _normalized_enum(item.get("source"), MISMATCH_DISCOVERY_SOURCES, {
                    "user_explanation": "later_user_explanation",
                    "test": "test_or_ci", "ci": "test_or_ci", "test_ci": "test_or_ci",
                    "test_or_ci_feedback": "test_or_ci", "error": "execution_error",
                    "output": "observed_output", "observed_output_feedback": "observed_output",
                    "repository": "project_invariant", "repo": "project_invariant",
                    "interface": "documentation", "docs": "documentation", "assistant": "agent_inference",
                    "user_preference_statement": "later_user_explanation",
                    "user_assumption_statement": "later_user_explanation",
                })
        counterfactual = thread.get("literal_counterfactual")
        if isinstance(counterfactual, dict):
            for field in ("surface_instruction_satisfied", "actual_situation_addressed",
                          "failure_caused_by_mismatch"):
                if counterfactual.get(field) is None:
                    counterfactual[field] = False
        response = thread.get("agent_gap_response")
        if isinstance(response, dict):
            for field in (
                "classification_evidence_sufficient", "considered_user_belief_or_goal",
                "identified_instruction_uncertainty", "asked_targeted_clarification",
                "identified_instruction_reality_gap", "challenged_or_deviated_from_instruction",
                "followed_surface_instruction", "proactive_before_user_explained_mismatch",
            ):
                if response.get(field) is None:
                    response[field] = False
            if response.get("evidence_turns") is None:
                response["evidence_turns"] = []
            if "surface_action_commitment_turn" not in response:
                response["surface_action_commitment_turn"] = None
            if response.get("detection_methods") is None:
                response["detection_methods"] = []
            if isinstance(response.get("detection_methods"), list):
                method_aliases = {
                    "user_question": "targeted_user_question", "clarification": "targeted_user_question",
                    "repository": "repository_inspection", "repo_inspection": "repository_inspection",
                    "documentation": "documentation_or_interface", "interface": "documentation_or_interface",
                    "test": "test_or_ci", "ci": "test_or_ci", "execution": "execution_or_error",
                    "execution_error": "execution_or_error", "prior_context": "prior_context_or_requirement",
                    "prior_requirement": "prior_context_or_requirement",
                    "compare_alternatives": "alternative_comparison", "reasoning": "causal_reasoning",
                }
                response["detection_methods"] = list(dict.fromkeys(
                    _normalized_enum(method, AGENT_DETECTION_METHODS, method_aliases)
                    for method in response["detection_methods"]
                ))
            if response.get("observed_resolution_status") is None:
                response["observed_resolution_status"] = "unknown"
            response["observed_resolution_status"] = _normalized_enum(
                response.get("observed_resolution_status"), RESOLUTION_STATUSES,
                {"satisfied": "resolved", "complete": "resolved", "completed": "resolved",
                 "failed": "unresolved", "failure": "unresolved", "unclear": "unknown"},
            )

        if thread.get("actual_situation_identifiable") is False:
            thread["actual_project_situation"] = ""
            thread["actual_situation_evidence"] = []
            _normalize_no_mismatch_fields(thread, "unclear")
            continue
        if thread.get("material_instruction_reality_mismatch") is False:
            _normalize_no_mismatch_fields(thread, "no_material_mismatch")
            continue

        if thread.get("user_belief_identifiable") is False:
            thread["user_belief"] = ""
            thread["belief_evidence"] = []
            thread["gap_driver"] = "unclear"
            thread["gap_driver_evidence_strength"] = "insufficient"
            thread["belief_basis_scope"] = "unclear"
            thread["driver_evidence"] = []
        elif (not thread.get("driver_evidence")
              and thread.get("gap_driver") != "assumption_without_stated_basis"):
            thread["gap_driver"] = "unclear"
            thread["gap_driver_evidence_strength"] = "insufficient"
        if thread.get("gap_driver") in {"unclear", "no_material_mismatch"}:
            thread["gap_driver_evidence_strength"] = "insufficient"

        if isinstance(discovery, dict):
            path = discovery.get("mismatch_evidence_path")
            if isinstance(path, list) and not path and isinstance(thread.get("actual_situation_evidence"), list):
                path.extend({
                    "turn": item.get("turn"), "source": item.get("source"),
                    "evidence": item.get("evidence", ""),
                } for item in thread["actual_situation_evidence"] if isinstance(item, dict))
            if isinstance(path, list) and path and all(
                isinstance(item, dict) and isinstance(item.get("turn"), int) for item in path
            ):
                path.sort(key=lambda item: item["turn"])
                discovery["earliest_mismatch_evidence_turn"] = path[0]["turn"]

        if isinstance(response, dict):
            detection_turn = response.get("reality_gap_detection_turn")
            clarification_turn = response.get("clarification_turn")
            resistance_turn = response.get("resistance_turn")
            commitment_turn = response.get("surface_action_commitment_turn")
            response["identified_instruction_reality_gap"] = detection_turn is not None
            response["asked_targeted_clarification"] = clarification_turn is not None
            if clarification_turn is not None:
                response["identified_instruction_uncertainty"] = True
            response["challenged_or_deviated_from_instruction"] = resistance_turn is not None
            if resistance_turn is not None and detection_turn is None:
                response["reality_gap_detection_turn"] = resistance_turn
                response["identified_instruction_reality_gap"] = True
                detection_turn = resistance_turn
            early_handling_turns = [turn for turn in (clarification_turn, resistance_turn)
                                    if isinstance(turn, int)]
            first_early_handling_turn = min(early_handling_turns) if early_handling_turns else None
            response["followed_surface_instruction"] = bool(
                isinstance(commitment_turn, int)
                and (first_early_handling_turn is None
                     or commitment_turn <= first_early_handling_turn)
            )
            issue_turns = [turn for turn in (detection_turn, clarification_turn, resistance_turn)
                           if isinstance(turn, int)]
            consideration_turn = response.get("mental_state_consideration_turn")
            if consideration_turn is None and issue_turns:
                consideration_turn = min(issue_turns)
                response["mental_state_consideration_turn"] = consideration_turn
            response["considered_user_belief_or_goal"] = consideration_turn is not None
            if consideration_turn is None:
                response["identified_instruction_uncertainty"] = False
                response["detection_methods"] = []
            user_signal_turns: list[int] = []
            if isinstance(discovery, dict):
                explanation_turn = discovery.get("first_user_mismatch_explanation_turn")
                if isinstance(explanation_turn, int):
                    user_signal_turns.append(explanation_turn)
                for item in discovery.get("mismatch_evidence_path", []):
                    if (isinstance(item, dict)
                            and item.get("source") in {
                                "later_user_explanation", "user_correction", "user_rejection",
                            }
                            and isinstance(item.get("turn"), int)):
                        user_signal_turns.append(item["turn"])
            first_user_signal_turn = min(user_signal_turns) if user_signal_turns else None
            all_issue_turns = [turn for turn in (consideration_turn, detection_turn,
                                                 clarification_turn, resistance_turn)
                               if isinstance(turn, int)]
            if not response.get("evidence_turns") and all_issue_turns:
                response["evidence_turns"] = sorted(set(all_issue_turns))
            if (response.get("classification_evidence_sufficient")
                    and not response.get("evidence_turns")):
                response["classification_evidence_sufficient"] = False
            response["proactive_before_user_explained_mismatch"] = bool(
                all_issue_turns
                and (not isinstance(commitment_turn, int)
                     or min(all_issue_turns) < commitment_turn)
                and (first_user_signal_turn is None
                     or min(all_issue_turns) < first_user_signal_turn)
            )
            if (response.get("observed_resolution_status") in {"resolved", "partial"}
                    and response.get("actual_situation_addressed_turn") is None):
                response["observed_resolution_status"] = "unknown"


def derive_agent_response_pattern(thread: dict[str, Any]) -> None:
    response = thread.get("agent_gap_response")
    if not isinstance(response, dict):
        return
    if not thread.get("material_instruction_reality_mismatch"):
        pattern = "no_material_mismatch"
    elif not response.get("classification_evidence_sufficient"):
        pattern = "unclear"
    else:
        commitment_turn = response.get("surface_action_commitment_turn")
        resistance_turn = response.get("resistance_turn")
        clarification_turn = response.get("clarification_turn")
        early_resistance = bool(
            response.get("identified_instruction_reality_gap")
            and response.get("challenged_or_deviated_from_instruction")
            and isinstance(resistance_turn, int)
            and (not isinstance(commitment_turn, int) or resistance_turn < commitment_turn)
        )
        early_clarification = bool(
            response.get("identified_instruction_uncertainty")
            and response.get("asked_targeted_clarification")
            and isinstance(clarification_turn, int)
            and (not isinstance(commitment_turn, int) or clarification_turn < commitment_turn)
        )
        if early_resistance:
            pattern = "detects_reality_gap_and_resists"
        elif early_clarification:
            pattern = "clarifies_instruction_uncertainty"
        elif response.get("followed_surface_instruction"):
            pattern = "follows_surface_instruction"
        else:
            pattern = "mixed_or_other"
    response["response_pattern"] = pattern


def validate_annotation(
    value: dict[str, Any], valid_turns: set[int], valid_user_turns: set[int] | None = None
) -> None:
    valid_user_turns = valid_user_turns if valid_user_turns is not None else valid_turns
    threads = value.get("task_threads")
    if not isinstance(threads, list) or not threads:
        raise ValueError("task_threads must be a non-empty list")
    task_ids: set[str] = set()
    initial_turns: set[int] = set()
    for thread in threads:
        task_id = thread.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in task_ids:
            raise ValueError("task_id must be a unique non-empty string")
        task_ids.add(task_id)
        initial_turn = thread.get("surface_instruction_turn")
        if initial_turn not in valid_user_turns or initial_turn in initial_turns:
            raise ValueError("surface_instruction_turn must be a unique user turn")
        initial_turns.add(initial_turn)
        if not isinstance(thread.get("surface_instruction"), str) or not thread["surface_instruction"]:
            raise ValueError("surface_instruction must be a non-empty string")
        flags = ("user_belief_identifiable", "actual_situation_identifiable",
                 "material_instruction_reality_mismatch")
        if any(not isinstance(thread.get(field), bool) for field in flags):
            raise ValueError("belief/mismatch annotation flags must be boolean")
        belief_evidence = thread.get("belief_evidence")
        if not isinstance(belief_evidence, list) or any(item.get("turn") not in valid_turns
                                                        for item in belief_evidence):
            raise ValueError("invalid belief_evidence")
        for item in belief_evidence:
            if item.get("source") not in BELIEF_EVIDENCE_SOURCES:
                raise _invalid_enum("belief_evidence[].source", item.get("source"), BELIEF_EVIDENCE_SOURCES)
        situation_evidence = thread.get("actual_situation_evidence")
        if not isinstance(situation_evidence, list) or any(item.get("turn") not in valid_turns
                                                           for item in situation_evidence):
            raise ValueError("invalid actual_situation_evidence")
        for item in situation_evidence:
            if item.get("source") not in ACTUAL_SITUATION_EVIDENCE_SOURCES:
                raise _invalid_enum(
                    "actual_situation_evidence[].source", item.get("source"),
                    ACTUAL_SITUATION_EVIDENCE_SOURCES,
                )
        mismatch_types = thread.get("mismatch_types")
        if not isinstance(mismatch_types, list):
            raise ValueError("invalid mismatch_types")
        invalid_mismatch_types = [item for item in mismatch_types if item not in MISMATCH_TYPES]
        if invalid_mismatch_types:
            raise _invalid_enum("mismatch_types[]", invalid_mismatch_types[0], MISMATCH_TYPES)
        discovery = thread.get("mismatch_discovery")
        if (not isinstance(discovery, dict)
                or discovery.get("initial_state_discoverability") not in
                INITIAL_DISCOVERABILITY_STATUSES):
            raise _invalid_enum(
                "mismatch_discovery.initial_state_discoverability",
                discovery.get("initial_state_discoverability") if isinstance(discovery, dict) else None,
                INITIAL_DISCOVERABILITY_STATUSES,
            )
        for field in ("earliest_mismatch_evidence_turn", "first_user_mismatch_explanation_turn"):
            if discovery.get(field) is not None and discovery[field] not in valid_turns:
                raise ValueError(f"{field} is absent from packet")
        if (discovery.get("first_user_mismatch_explanation_turn") is not None
                and discovery["first_user_mismatch_explanation_turn"] not in valid_user_turns):
            raise ValueError("first_user_mismatch_explanation_turn must be a user turn")
        discovery_path = discovery.get("mismatch_evidence_path")
        if not isinstance(discovery_path, list) or any(item.get("turn") not in valid_turns
                                                       for item in discovery_path):
            raise ValueError("invalid mismatch_evidence_path")
        for item in discovery_path:
            if item.get("source") not in MISMATCH_DISCOVERY_SOURCES:
                raise _invalid_enum(
                    "mismatch_evidence_path[].source", item.get("source"), MISMATCH_DISCOVERY_SOURCES,
                )
        path_turns = [item.get("turn") for item in discovery_path]
        if path_turns != sorted(path_turns):
            raise ValueError("mismatch_evidence_path must be chronological")
        if thread.get("gap_driver") not in GAP_DRIVERS:
            raise _invalid_enum("gap_driver", thread.get("gap_driver"), GAP_DRIVERS)
        if thread.get("gap_driver_evidence_strength") not in DRIVER_EVIDENCE_STRENGTHS:
            raise _invalid_enum(
                "gap_driver_evidence_strength", thread.get("gap_driver_evidence_strength"),
                DRIVER_EVIDENCE_STRENGTHS,
            )
        if thread.get("belief_basis_scope") not in BELIEF_BASIS_SCOPES:
            raise _invalid_enum("belief_basis_scope", thread.get("belief_basis_scope"), BELIEF_BASIS_SCOPES)
        driver_evidence = thread.get("driver_evidence")
        if not isinstance(driver_evidence, list) or any(item.get("turn") not in valid_turns for item in driver_evidence):
            raise ValueError("invalid driver_evidence")

        counterfactual = thread.get("literal_counterfactual")
        counter_fields = ("surface_instruction_satisfied", "actual_situation_addressed",
                          "failure_caused_by_mismatch")
        if not isinstance(counterfactual, dict) or any(
            not isinstance(counterfactual.get(field), bool) for field in counter_fields
        ):
            raise ValueError("literal_counterfactual must contain booleans")
        response = thread.get("agent_gap_response")
        response_flags = (
            "classification_evidence_sufficient", "considered_user_belief_or_goal",
            "identified_instruction_uncertainty", "asked_targeted_clarification",
            "identified_instruction_reality_gap", "challenged_or_deviated_from_instruction",
            "followed_surface_instruction", "proactive_before_user_explained_mismatch",
        )
        if not isinstance(response, dict) or any(
            not isinstance(response.get(field), bool) for field in response_flags
        ):
            raise ValueError("agent_gap_response needs boolean atomic fields")
        response_evidence = response.get("evidence_turns")
        if not isinstance(response_evidence, list) or any(turn not in valid_turns for turn in response_evidence):
            raise ValueError("invalid agent response evidence turns")
        response_turn_fields = (
            "mental_state_consideration_turn", "reality_gap_detection_turn", "clarification_turn",
            "resistance_turn", "surface_action_commitment_turn", "actual_situation_addressed_turn",
        )
        for field in response_turn_fields:
            if response.get(field) is not None and response[field] not in valid_turns:
                raise ValueError(f"{field} is absent from packet")
        methods = response.get("detection_methods")
        if not isinstance(methods, list):
            raise ValueError("invalid agent detection_methods")
        invalid_methods = [method for method in methods if method not in AGENT_DETECTION_METHODS]
        if invalid_methods:
            raise _invalid_enum("detection_methods[]", invalid_methods[0], AGENT_DETECTION_METHODS)
        if response.get("observed_resolution_status") not in RESOLUTION_STATUSES:
            raise _invalid_enum(
                "observed_resolution_status", response.get("observed_resolution_status"),
                RESOLUTION_STATUSES,
            )

        if thread["user_belief_identifiable"]:
            if not isinstance(thread.get("user_belief"), str) or not thread["user_belief"] or not belief_evidence:
                raise ValueError("identifiable user belief needs text and evidence")
        else:
            if belief_evidence or thread.get("user_belief"):
                raise ValueError("unidentifiable user belief must not contain inferred belief evidence")
            if thread["gap_driver"] not in {"unclear", "no_material_mismatch"}:
                raise ValueError("unidentifiable user belief cannot have a specific driver")
            if thread.get("belief_basis_scope") not in {"unclear", "not_applicable"}:
                raise ValueError("unidentifiable user belief cannot have a specific belief basis scope")

        if thread["actual_situation_identifiable"]:
            if (not isinstance(thread.get("actual_project_situation"), str)
                    or not thread["actual_project_situation"] or not situation_evidence):
                raise ValueError("identifiable actual situation needs text and evidence")
            if thread["material_instruction_reality_mismatch"]:
                if not mismatch_types or "no_material_mismatch" in mismatch_types:
                    raise ValueError("material mismatch needs material mismatch types")
                if thread["gap_driver"] == "no_material_mismatch":
                    raise ValueError("material mismatch cannot use no-mismatch driver")
                if thread.get("belief_basis_scope") == "not_applicable":
                    raise ValueError("material mismatch needs a belief basis scope or unclear")
                if (discovery.get("earliest_mismatch_evidence_turn") is None
                        or not discovery_path
                        or discovery["earliest_mismatch_evidence_turn"] != path_turns[0]):
                    raise ValueError("material mismatch needs a path starting at earliest evidence")
            else:
                if mismatch_types != ["no_material_mismatch"]:
                    raise ValueError("no mismatch must use no_material_mismatch type")
                if thread["gap_driver"] != "no_material_mismatch":
                    raise ValueError("no mismatch must use no_material_mismatch driver")
                if thread.get("belief_basis_scope") != "not_applicable":
                    raise ValueError("no mismatch must use not_applicable belief basis scope")
                if driver_evidence:
                    raise ValueError("no mismatch must not contain driver evidence")
                if any(response.get(field) for field in response_flags):
                    raise ValueError("no mismatch must have false response flags")
                if (discovery["initial_state_discoverability"] != "not_applicable"
                        or discovery.get("earliest_mismatch_evidence_turn") is not None
                        or discovery.get("first_user_mismatch_explanation_turn") is not None
                        or discovery_path):
                    raise ValueError("no mismatch must have empty discovery fields")
        else:
            if situation_evidence or mismatch_types or thread.get("actual_project_situation"):
                raise ValueError("unidentifiable actual situation must not contain inferred situation")
            if thread["material_instruction_reality_mismatch"] or any(counterfactual.values()):
                raise ValueError("unidentifiable actual situation cannot assert mismatch")
            if thread["gap_driver"] != "unclear" or driver_evidence:
                raise ValueError("unidentifiable actual situation must use unclear driver")
            if thread.get("belief_basis_scope") != "not_applicable":
                raise ValueError("unidentifiable actual situation must use not_applicable belief basis scope")
            if (discovery["initial_state_discoverability"] != "not_applicable"
                    or discovery.get("earliest_mismatch_evidence_turn") is not None
                    or discovery.get("first_user_mismatch_explanation_turn") is not None
                    or discovery_path):
                raise ValueError("unidentifiable actual situation must have empty discovery fields")

        if thread["gap_driver_evidence_strength"] in {"explicit", "strong_inference", "weak_inference"}:
            if thread["gap_driver"] in {"unclear", "no_material_mismatch"} or not driver_evidence:
                raise ValueError("supported belief driver needs a specific driver and evidence")
        elif thread["gap_driver"] not in {"unclear", "assumption_without_stated_basis",
                                          "no_material_mismatch"}:
            raise ValueError("specific belief driver needs supporting evidence")

        if counterfactual["failure_caused_by_mismatch"] and not (
            thread["material_instruction_reality_mismatch"]
            and counterfactual["surface_instruction_satisfied"]
            and not counterfactual["actual_situation_addressed"]
        ):
            raise ValueError("instruction-reality counterfactual is inconsistent")
        if response["asked_targeted_clarification"] and not response["identified_instruction_uncertainty"]:
            raise ValueError("targeted clarification requires identified uncertainty")
        if (response["identified_instruction_uncertainty"]
                or response["asked_targeted_clarification"]
                or response["identified_instruction_reality_gap"]):
            if not response["considered_user_belief_or_goal"]:
                raise ValueError(
                    "instruction uncertainty, clarification, or gap detection requires "
                    "user-belief consideration"
                )
        if response["challenged_or_deviated_from_instruction"] and not response["identified_instruction_reality_gap"]:
            raise ValueError("gap-aware resistance requires identified reality gap")
        turn_flag_pairs = (
            ("considered_user_belief_or_goal", "mental_state_consideration_turn"),
            ("identified_instruction_reality_gap", "reality_gap_detection_turn"),
            ("asked_targeted_clarification", "clarification_turn"),
            ("challenged_or_deviated_from_instruction", "resistance_turn"),
        )
        for flag, turn_field in turn_flag_pairs:
            if response[flag] != (response.get(turn_field) is not None):
                raise ValueError(f"{flag} and {turn_field} must agree")
        issue_turns = [response[field] for field in (
            "mental_state_consideration_turn", "reality_gap_detection_turn",
            "clarification_turn", "resistance_turn",
        ) if response.get(field) is not None]
        user_signal_turns = [
            item["turn"] for item in discovery_path
            if item.get("source") in {
                "later_user_explanation", "user_correction", "user_rejection",
            }
        ]
        if isinstance(discovery.get("first_user_mismatch_explanation_turn"), int):
            user_signal_turns.append(discovery["first_user_mismatch_explanation_turn"])
        first_user_signal_turn = min(user_signal_turns) if user_signal_turns else None
        commitment_turn = response.get("surface_action_commitment_turn")
        handling_turns = [response[field] for field in ("clarification_turn", "resistance_turn")
                          if response.get(field) is not None]
        first_handling_turn = min(handling_turns) if handling_turns else None
        expected_followed = bool(
            isinstance(commitment_turn, int)
            and (first_handling_turn is None or commitment_turn <= first_handling_turn)
        )
        if response["followed_surface_instruction"] != expected_followed:
            raise ValueError("followed-surface flag conflicts with commitment/handling timing")
        expected_proactive = bool(
            issue_turns
            and (not isinstance(commitment_turn, int) or min(issue_turns) < commitment_turn)
            and (first_user_signal_turn is None or min(issue_turns) < first_user_signal_turn)
        )
        if response["proactive_before_user_explained_mismatch"] != expected_proactive:
            raise ValueError("proactive flag conflicts with agent/user timing")
        resolution_status = response["observed_resolution_status"]
        addressed_turn = response.get("actual_situation_addressed_turn")
        if resolution_status in {"resolved", "partial"} and addressed_turn is None:
            raise ValueError("resolved/partial status needs actual_situation_addressed_turn")
        if not thread["material_instruction_reality_mismatch"] and (
            any(response.get(field) is not None for field in response_turn_fields)
            or methods or resolution_status != "unknown"
        ):
            raise ValueError("no mismatch must have null/empty response details")
        if (thread["material_instruction_reality_mismatch"]
                and response["classification_evidence_sufficient"]
                and not response_evidence):
            raise ValueError("classifiable mismatch response needs evidence")
        derive_agent_response_pattern(thread)
        if response["response_pattern"] not in AGENT_RESPONSE_PATTERNS:
            raise ValueError("invalid derived response pattern")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be numeric in [0,1]")


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"estimate": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator}


def _numeric_summary(values: list[Any]) -> dict[str, Any]:
    clean = [float(value) for value in values if isinstance(value, (int, float))
             and not isinstance(value, bool) and isfinite(float(value))]
    return {"mean": mean(clean) if clean else None,
            "median": median(clean) if clean else None, "n": len(clean)}


def _comparison(exposed: list[Any], comparator: list[Any]) -> dict[str, Any]:
    left, right = _numeric_summary(exposed), _numeric_summary(comparator)
    return {
        "faithful_execution_under_mismatch": left,
        "early_clarification_or_resistance": right,
        "mean_difference_faithful_minus_early_handling": (
            left["mean"] - right["mean"]
            if left["mean"] is not None and right["mean"] is not None else None
        ),
    }


def _timestamp_seconds(turn_timestamps: dict[str, Any], start: int, end: int) -> float | None:
    try:
        a = datetime.fromisoformat(str(turn_timestamps[str(start)]).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(turn_timestamps[str(end)]).replace("Z", "+00:00"))
        return max(0.0, (b - a).total_seconds())
    except (KeyError, TypeError, ValueError):
        return None


def _latency(records: list[tuple[dict[str, Any], dict[str, Any]]], end_field: str) -> dict[str, Any]:
    turns: list[int] = []
    seconds: list[float] = []
    unresolved = 0
    for row, thread in records:
        start = thread.get("mismatch_discovery", {}).get("earliest_mismatch_evidence_turn")
        end = thread.get("agent_gap_response", {}).get(end_field)
        if isinstance(start, int) and isinstance(end, int) and end >= start:
            turns.append(end - start)
            elapsed = _timestamp_seconds(row.get("turn_timestamps", {}), start, end)
            if elapsed is not None:
                seconds.append(elapsed)
        else:
            unresolved += 1
    return {
        "turns": _numeric_summary(turns), "seconds": _numeric_summary(seconds),
        "unresolved_or_unobservable_count": unresolved, "eligible_mismatch_count": len(records),
    }


def aggregate_study2(rows: list[dict[str, Any]]) -> dict[str, Any]:
    records = [(row, thread) for row in rows if isinstance(row.get("annotation"), dict)
               for thread in row["annotation"].get("task_threads", [])]
    identifiable = [(row, thread) for row, thread in records
                    if thread.get("actual_situation_identifiable") is True]
    gaps = [(row, thread) for row, thread in identifiable
            if thread.get("material_instruction_reality_mismatch") is True]
    gap_threads = [thread for _, thread in gaps]
    literal_failures = [thread for _, thread in identifiable
                        if thread.get("literal_counterfactual", {}).get("surface_instruction_satisfied") is True
                        and thread.get("literal_counterfactual", {}).get("actual_situation_addressed") is False
                        and thread.get("literal_counterfactual", {}).get("failure_caused_by_mismatch") is True]
    mismatch_type_distribution: Counter[str] = Counter()
    for thread in gap_threads:
        mismatch_type_distribution.update(thread.get("mismatch_types", []))
    driver_distribution = Counter(thread.get("gap_driver", "unclear") for thread in gap_threads)
    driver_strength_distribution = Counter(thread.get("gap_driver_evidence_strength", "insufficient")
                                           for thread in gap_threads)
    belief_scope_distribution = Counter(thread.get("belief_basis_scope", "unclear")
                                        for thread in gap_threads)
    classifiable_belief_scope = sum(belief_scope_distribution[scope] for scope in (
        "partial_observation", "broadly_grounded", "non_observational",
    ))
    identifiable_beliefs = [thread for thread in gap_threads if thread.get("user_belief_identifiable") is True]
    considered = [thread for thread in gap_threads
                  if thread.get("agent_gap_response", {}).get("considered_user_belief_or_goal") is True]
    proactive = [thread for thread in gap_threads
                 if thread.get("agent_gap_response", {}).get("proactive_before_user_explained_mismatch") is True]
    response_distribution = Counter(thread.get("agent_gap_response", {}).get("response_pattern", "unclear")
                                    for thread in gap_threads)
    principal_patterns = (
        "follows_surface_instruction", "clarifies_instruction_uncertainty",
        "detects_reality_gap_and_resists",
    )

    discoverability_distribution = Counter(
        thread.get("mismatch_discovery", {}).get("initial_state_discoverability", "unclear")
        for thread in gap_threads
    )
    classifiable_discoverability = (
        discoverability_distribution["discoverable"]
        + discoverability_distribution["not_discoverable"]
    )
    with_user_explanation = [thread for thread in gap_threads
                             if isinstance(thread.get("mismatch_discovery", {}).get(
                                 "first_user_mismatch_explanation_turn"), int)]
    discoverable_before_user = [thread for thread in with_user_explanation
                                if thread["mismatch_discovery"]["earliest_mismatch_evidence_turn"]
                                < thread["mismatch_discovery"]["first_user_mismatch_explanation_turn"]]
    proactive_detection = [
        thread for thread in gap_threads
        if thread.get("agent_gap_response", {}).get(
            "proactive_before_user_explained_mismatch"
        ) is True
        and thread.get("agent_gap_response", {}).get(
            "identified_instruction_reality_gap"
        ) is True
    ]
    discovery_sources: Counter[str] = Counter()
    detection_methods: Counter[str] = Counter()
    for thread in gap_threads:
        discovery_sources.update(item.get("source", "unclear") for item in
                                 thread.get("mismatch_discovery", {}).get("mismatch_evidence_path", []))
        detection_methods.update(thread.get("agent_gap_response", {}).get("detection_methods", []))

    outcome_by_pattern: dict[str, Any] = {}
    for pattern in (*principal_patterns, "mixed_or_other", "unclear"):
        matching = [thread for thread in gap_threads
                    if thread.get("agent_gap_response", {}).get("response_pattern") == pattern]
        statuses = Counter(thread.get("agent_gap_response", {}).get(
            "observed_resolution_status", "unknown") for thread in matching)
        known = sum(statuses[status] for status in ("resolved", "partial", "unresolved"))
        outcome_by_pattern[pattern] = {
            "resolved_rate": {**_rate(statuses["resolved"], known),
                              "unit": "mismatch_thread_with_observed_resolution"},
            "status_distribution": dict(sorted(statuses.items())),
        }

    rows_by_session = {str(row.get("session_id")): row for row, _ in gaps}
    threads_by_session: dict[str, list[dict[str, Any]]] = {}
    for row, thread in gaps:
        threads_by_session.setdefault(str(row.get("session_id")), []).append(thread)
    faithful_sessions = {
        sid for sid, session_threads in threads_by_session.items()
        if any(thread.get("agent_gap_response", {}).get("followed_surface_instruction") is True
               for thread in session_threads)
    }
    early_handling_sessions = {
        sid for sid, session_threads in threads_by_session.items()
        if sid not in faithful_sessions and any(
            thread.get("agent_gap_response", {}).get("response_pattern") in {
                "clarifies_instruction_uncertainty", "detects_reality_gap_and_resists",
            } for thread in session_threads
        )
    }
    cost_comparisons: dict[str, Any] = {}
    for field in (
        "human_rework_lines", "linked_commit_deletions", "committed_agent_code_share",
        "turn_count", "tool_call_count", "api_call_count", "total_tokens", "duration_seconds",
    ):
        cost_comparisons[field] = _comparison(
            [rows_by_session[sid].get("observed_costs", {}).get(field) for sid in faithful_sessions],
            [rows_by_session[sid].get("observed_costs", {}).get(field)
             for sid in early_handling_sessions],
        )

    return {
        "material_instruction_reality_mismatch_rate": {
            **_rate(len(gaps), len(identifiable)), "unit": "task_thread_with_identifiable_actual_situation",
            "unidentifiable_actual_situation_task_thread_count": len(records) - len(identifiable),
            "mismatch_type_distribution": dict(sorted(mismatch_type_distribution.items())),
        },
        "gap_driver": {
            "distribution": dict(sorted(driver_distribution.items())),
            "evidence_strength_distribution": dict(sorted(driver_strength_distribution.items())),
            "belief_basis_scope_distribution": dict(sorted(belief_scope_distribution.items())),
            "partial_observation_belief_rate": {
                **_rate(belief_scope_distribution["partial_observation"], classifiable_belief_scope),
                "unit": "material_mismatch_thread_with_classifiable_belief_basis",
                "unclear_count": belief_scope_distribution["unclear"],
            },
            "user_belief_identifiable_rate": {**_rate(len(identifiable_beliefs), len(gaps)),
                                               "unit": "material_mismatch_task_thread"},
        },
        "mismatch_discoverability_and_route": {
            "initially_discoverable_rate": {
                **_rate(discoverability_distribution["discoverable"], classifiable_discoverability),
                "unit": "material_mismatch_task_thread_with_classifiable_initial_discoverability",
                "unclear_count": discoverability_distribution["unclear"],
            },
            "initial_state_discoverability_distribution": dict(
                sorted(discoverability_distribution.items())
            ),
            "discoverable_before_user_explanation_rate": {
                **_rate(len(discoverable_before_user), len(with_user_explanation)),
                "unit": "material_mismatch_thread_with_user_explanation",
            },
            "evidence_path_source_distribution": dict(sorted(discovery_sources.items())),
            "agent_detection_method_distribution": dict(sorted(detection_methods.items())),
        },
        "literal_compliance_but_reality_failure_rate": {
            **_rate(len(literal_failures), len(identifiable)),
            "unit": "task_thread_with_identifiable_actual_situation",
        },
        "agent_gap_detection_and_response": {
            "unit": "material_instruction_reality_mismatch_task_thread",
            "user_mental_state_consideration_rate": _rate(len(considered), len(gaps)),
            "proactive_consideration_or_detection_rate": _rate(len(proactive), len(gaps)),
            "proactive_reality_gap_detection_rate": _rate(len(proactive_detection), len(gaps)),
            "response_pattern_distribution": dict(sorted(response_distribution.items())),
            "response_pattern_rates": {
                pattern: _rate(sum(
                    thread.get("agent_gap_response", {}).get("response_pattern") == pattern
                    for thread in gap_threads
                ), len(gaps))
                for pattern in principal_patterns
            },
            "mixed_or_other_rate": _rate(response_distribution["mixed_or_other"], len(gaps)),
            "unclassified_count": response_distribution["unclear"],
            "evidence_to_mental_state_consideration_latency": _latency(
                gaps, "mental_state_consideration_turn"
            ),
            "evidence_to_reality_gap_detection_latency": _latency(
                gaps, "reality_gap_detection_turn"
            ),
            "evidence_to_actual_situation_addressed_latency": _latency(
                gaps, "actual_situation_addressed_turn"
            ),
        },
        "observed_resolution_by_agent_response": outcome_by_pattern,
        "cost_of_faithful_execution_under_mismatch": {
            "exposure_definition": (
                "session contains a material mismatch thread where the agent substantially followed "
                "the surface instruction before resolving the mismatch"
            ),
            "comparator_definition": (
                "mismatch session with no faithful-execution exposure and at least one early targeted "
                "clarification or evidence-based resistance response"
            ),
            "faithful_execution_session_count": len(faithful_sessions),
            "early_handling_session_count": len(early_handling_sessions),
            "excluded_mixed_or_unclassified_session_count": (
                len(threads_by_session) - len(faithful_sessions) - len(early_handling_sessions)
            ),
            "session_level_descriptive_comparisons": cost_comparisons,
            "code_measurement_note": (
                "descriptive association only; human_rework_lines=human_modified+human_removed; "
                "linked commits may cover multiple sessions; committed_agent_code_share is an "
                "authorship-based survival proxy"
            ),
        },
    }
