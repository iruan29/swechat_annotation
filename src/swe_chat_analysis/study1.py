from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import isfinite
import re
from statistics import mean, median
from typing import Any


STUDY1_RUBRIC_VERSION = "requirement_response_v3"
STUDY1_REQUIREMENTS_RUBRIC_VERSION = "requirement_evolution_v5"

MATERIAL_EVENT_TYPES = {
    "user_goal_change", "requirement_revelation",
    "environment_constraint_discovery", "correction",
}
EVENT_TYPES = MATERIAL_EVENT_TYPES | {"non_material_refinement", "process_only", "new_task"}
ARTICULATION_SOURCES = {"user", "agent", "tool", "repository", "review"}
REQUIREMENT_BASES = {"project_grounded", "user_preference", "mixed", "unclear"}
DISCOVERY_STATUSES = {
    "explicit_initially", "discoverable_initially", "became_discoverable_later",
    "preference_only_when_articulated", "not_discoverable_from_available_evidence", "unclear",
}
DISCOVERY_EVIDENCE_SOURCES = {
    "initial_instruction", "user_update", "repository", "documentation", "test_or_ci",
    "execution_error", "observed_output", "review", "agent_inference",
}
USER_REQUIREMENT_TRIGGERS = {
    "execution_error", "test_or_ci_feedback", "observed_output_feedback",
    "repository_or_dependency_constraint", "agent_explanation_or_proposal",
    "review_or_external_feedback", "spontaneous_user_revision", "unclear",
    "not_user_articulated",
}
OBSERVATION_OR_FEEDBACK_TRIGGERS = USER_REQUIREMENT_TRIGGERS - {
    "spontaneous_user_revision", "unclear", "not_user_articulated",
}
CAUSAL_LINK_STRENGTHS = {"explicit", "strong", "weak", "none"}
IMPLEMENTATION_STATUSES = {"satisfied", "partial", "failed", "unknown", "not_applicable"}
AGENT_RESPONSES = {
    "anticipated_and_satisfied", "proactive_question_then_satisfied",
    "correctly_updated_after_new_evidence", "surface_symptom_patch",
    "ignored_new_evidence", "satisfied_new_but_regressed_existing",
    "unclear_or_unresolved", "not_applicable",
}
BEHAVIOR_MODES = (
    "reactive_instruction_following", "instruction_scoped_sensemaking",
    "project_level_requirement_discovery",
)
RESOLUTION_METHODS = {
    "user_question", "repository_evidence", "execution_evidence",
    "prior_requirement", "alternative_comparison",
}


REQUIREMENTS_SYSTEM_PROMPT = r"""You are neutrally annotating longitudinal requirement
formation and agent response in a real software-engineering session. Use only observable evidence.
The hypotheses may be false. Do not manufacture requirements, grounding, causality, or success.

Unit and materiality:
- Split the session into task threads. A later independent objective is a new thread, not evolution.
- The initial instruction is the first substantive user request in a thread.
- A material requirement changes acceptable end states: externally visible behavior, important
  scope, compatibility/project constraints, or acceptance criteria. Process requests, approvals,
  wording refinements, and implementation details with no outcome effect are not material.
- Give every final material requirement a stable ID (R1, R2, ...). Events may reuse an ID;
  non-material/new-task events use requirement_id=null.

Initial instruction specificity:
- Score how fully the initial wording states what is needed to judge the final artifact:
  4=all material requirements explicit; 3=only minor acceptance detail omitted; 2=core goal stated
  but an important requirement omitted; 1=most acceptance-defining requirements absent;
  0=incompatible or final requirements unidentifiable.
- present_in_initial_instruction requires textual entailment, not later project inference.

Requirement basis:
- project_grounded: required by code/interfaces, tests, docs, runtime/build/dependencies, established
  functional purpose, or a concrete defect; it matters independent of idiosyncratic taste.
- user_preference: several project-compatible outcomes remain and acceptability depends on the
  user's taste, workflow, convention, or discretionary scope choice.
- mixed: project constraint and discretionary choice are inseparable. unclear: evidence cannot tell.
A requirement is not preference merely because a user says it, nor grounded because it was coded.

Events and triggers:
- user_goal_change changes outcome/scope; requirement_revelation makes an unstated requirement
  explicit; environment_constraint_discovery exposes a code/runtime/build/API constraint;
  correction establishes a prior interpretation/result was materially wrong.
- Also audit non_material_refinement, process_only, and new_task with material=false.
- articulation_source says who first makes the requirement/evidence explicit at that event.
- user_requirement_trigger and causal_link_strength describe observable evidence, never private
  mental state. Explicit/strong observation claims require trigger_turns.
- user_requirement_trigger applies only to user-articulated events. If articulation_source is not
  user, always use user_requirement_trigger=not_user_articulated, causal_link_strength=none, and
  trigger_turns=[]. For a user-articulated observation/feedback trigger, explicit or strong requires
  at least one supplied trigger turn. Use weak when the proposed link lacks a cited trigger turn.
- Non-material events may use first_explicit_turn=null because they do not establish a requirement.

Discoverability:
- first_explicit_turn is when the requirement first becomes explicit in the trace.
- earliest_discoverable_turn is the earliest supplied turn at which a competent autonomous agent
  could reasonably infer it from then-available evidence; null for discretionary preferences or
  when no defensible point exists.
- discovery_status is explicit_initially, discoverable_initially, became_discoverable_later,
  preference_only_when_articulated, not_discoverable_from_available_evidence, or unclear.
- discovery_evidence_path is a chronological causal chain from earliest clue to confirmation.
- inferable_before_revelation=true exactly when earliest_discoverable_turn < first_explicit_turn.

Agent response:
- agent_recognition_turn is the first turn identifying the actual requirement, not a symptom.
  correct_implementation_turn is the first supplied turn evidencing correct implementation; null
  if absent/unknown. Commit metadata corroborates but cannot create a transcript turn.
- Choose one response, using this precedence: satisfied_new_but_regressed_existing (new requirement
  met but another established requirement broken); anticipated_and_satisfied (recognized and met
  before explicit instruction); proactive_question_then_satisfied (targeted question elicited it,
  then met); correctly_updated_after_new_evidence; surface_symptom_patch; ignored_new_evidence;
  otherwise unclear_or_unresolved. Non-material events use not_applicable.
- List distinct broken requirement IDs in regressed_requirement_ids.

Evidence discipline:
- User correction/rejection, tests/errors, review, docs/interfaces, and repository invariants can
  establish requirements. An agent proposal or commit alone cannot.
- Copy turns only from T<number> labels. Never invent a turn or convert a commit hash to one.
- If truncation prevents judgment, use null/unknown and evidence_sufficient=false. Do not guess.

Exact enum contract (copy these values exactly):
- event_type: user_goal_change, requirement_revelation, environment_constraint_discovery,
  correction, non_material_refinement, process_only, new_task.
- articulation_source: user, agent, tool, repository, review.
- requirement_basis and final_requirements[].basis: project_grounded, user_preference, mixed, unclear.
- user_requirement_trigger: execution_error, test_or_ci_feedback, observed_output_feedback,
  repository_or_dependency_constraint, agent_explanation_or_proposal, review_or_external_feedback,
  spontaneous_user_revision, unclear, not_user_articulated.
- causal_link_strength: explicit, strong, weak, none.
- discovery_status: explicit_initially, discoverable_initially, became_discoverable_later,
  preference_only_when_articulated, not_discoverable_from_available_evidence, unclear.
- discovery_evidence_path[].source: initial_instruction, user_update, repository, documentation,
  test_or_ci, execution_error, observed_output, review, agent_inference.
- implementation_status: satisfied, partial, failed, unknown, not_applicable.
- agent_response: anticipated_and_satisfied, proactive_question_then_satisfied,
  correctly_updated_after_new_evidence, surface_symptom_patch, ignored_new_evidence,
  satisfied_new_but_regressed_existing, unclear_or_unresolved, not_applicable.

Return exactly one JSON object:
{
  "task_threads": [{
    "task_id": "task_1",
    "initial_instruction_turn": 0,
    "initial_requirements": ["string"],
    "initial_instruction_specificity": {
      "score": 0,
      "explicit_final_requirement_ids": ["R1"],
      "missing_final_requirement_ids": ["R2"],
      "rationale": "string"
    },
    "final_requirements": [
      {"requirement_id": "R1", "requirement": "initially explicit behavior",
       "basis": "project_grounded", "present_in_initial_instruction": true,
       "evidence_turns": [0]},
      {"requirement_id": "R2", "requirement": "later streaming constraint",
       "basis": "project_grounded", "present_in_initial_instruction": false,
       "evidence_turns": [1, 3]}
    ],
    "requirement_events": [{
      "turn": 3, "first_explicit_turn": 3, "requirement_id": "R2",
      "requirement": "string", "event_type": "requirement_revelation",
      "articulation_source": "user", "requirement_basis": "project_grounded",
      "basis_evidence_turns": [1, 3], "user_requirement_trigger": "execution_error",
      "causal_link_strength": "strong", "trigger_turns": [1], "same_task": true,
      "material": true, "discovery_status": "discoverable_initially",
      "earliest_discoverable_turn": 0, "inferable_before_revelation": true,
      "discovery_evidence_path": [
        {"turn": 0, "source": "initial_instruction", "evidence": "string"},
        {"turn": 3, "source": "user_update", "evidence": "string"}
      ],
      "agent_recognition_turn": 3, "correct_implementation_turn": 5,
      "implementation_status": "satisfied",
      "agent_response": "correctly_updated_after_new_evidence",
      "regressed_requirement_ids": [], "response_evidence_turns": [3, 5],
      "evidence_turns": [1, 3, 5]
    }],
    "literal_initial_completion_satisfies_final_requirements": false,
    "evidence_sufficient": true, "rationale": "string"
  }],
  "confidence": 0.0
}
Use null for unavailable turns. Use JSON primitives and no markdown."""


BEHAVIOR_SYSTEM_PROMPT = r"""You are neutrally annotating one instruction episode from a real
software-engineering session. You see only evidence available through this episode. Never use
later corrections, failures, requirements, commits, or outcomes.

The episode starts at TARGET_INSTRUCTION_TURN and ends before the next user instruction.
episode_in_scope=false for greetings, acknowledgements, injected/status-only content, or no task.
project_reasoning_opportunity=true only if available evidence presents an important ambiguity,
conflict, hidden constraint, downstream impact, or sign literal compliance may be wrong.

The pipeline derives one mode:
- reactive_instruction_following: executes/reacts without resolving an important uncertainty or
  discovering an unstated project requirement. File lookup, routine tests, restatement, permission
  questions, and applying an already specified fix remain here.
- instruction_scoped_sensemaking: identifies and resolves an important ambiguity, unknown, choice,
  or failure cause while preserving the stated material goal/scope/acceptance criteria.
- project_level_requirement_discovery: uses project evidence to identify an unstated material
  requirement/purpose/downstream effect and materially changes plan, scope, strategy, or acceptance.
Unsupported expansion and merely applying a supplied requirement do not count.

Set classification_evidence_sufficient=false only when evidence is absent/truncated or genuinely
indeterminate. Copy evidence turns only from T<number> labels.
Exact enum contract: every resolution_methods item must be one of user_question,
repository_evidence, execution_evidence, prior_requirement, alternative_comparison.
Return exactly one JSON object:
{
  "episode_in_scope": true, "instruction_turn": 0, "instruction_summary": "string",
  "project_reasoning_opportunity": true, "opportunity_reason": "string",
  "classification_evidence_sufficient": true, "important_uncertainty_identified": false,
  "resolution_methods": ["repository_evidence"], "instruction_scope_preserved": true,
  "project_evidence_used": false,
  "unstated_material_requirement_or_downstream_impact_identified": false,
  "material_plan_scope_strategy_or_acceptance_affected": false,
  "proactive_before_explicit_correction": false, "rationale": "string",
  "evidence": [{"turn": 0, "speaker_or_source": "assistant", "quote_or_paraphrase": "max 180 chars"}]
}
Do not output a level or mode. Use JSON primitives and no markdown."""


def requirements_user_prompt(packet_text: str) -> str:
    return "Annotate requirement specificity, grounding, discovery, and response.\n\n" + packet_text


def behavior_user_prompt(prefix_text: str, instruction_turn: int) -> str:
    return (f"TARGET_INSTRUCTION_TURN=T{instruction_turn}\n"
            "Classify only that response using evidence available so far.\n\n" + prefix_text)


def _normalized_enum(value: Any, allowed: set[str], aliases: dict[str, str] | None = None) -> Any:
    if not isinstance(value, str):
        return value
    token = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    token = (aliases or {}).get(token, token)
    return token if token in allowed else value


def _invalid_enum(field: str, value: Any, allowed: set[str]) -> ValueError:
    return ValueError(f"invalid {field}={value!r}; allowed={sorted(allowed)}")


def normalize_requirements_annotation(value: dict[str, Any]) -> None:
    for thread in value.get("task_threads", []):
        for field in ("literal_initial_completion_satisfies_final_requirements", "evidence_sufficient"):
            if thread.get(field) is None:
                thread[field] = False
        for event in thread.get("requirement_events", []):
            for field in ("same_task", "material", "inferable_before_revelation"):
                if event.get(field) is None:
                    event[field] = False
            for field in ("trigger_turns", "basis_evidence_turns", "discovery_evidence_path",
                          "regressed_requirement_ids", "response_evidence_turns", "evidence_turns"):
                if event.get(field) is None:
                    event[field] = []
        for requirement in thread.get("final_requirements", []):
            requirement["basis"] = _normalized_enum(
                requirement.get("basis"), REQUIREMENT_BASES,
                {"preference": "user_preference", "project_constraint": "project_grounded"},
            )
        for event in thread.get("requirement_events", []):
            event["event_type"] = _normalized_enum(event.get("event_type"), EVENT_TYPES, {
                "goal_change": "user_goal_change", "constraint_discovery": "environment_constraint_discovery",
                "refinement": "non_material_refinement", "new_independent_task": "new_task",
            })
            event["articulation_source"] = _normalized_enum(
                event.get("articulation_source"), ARTICULATION_SOURCES,
                {"assistant": "agent", "repo": "repository", "codebase": "repository"},
            )
            event["requirement_basis"] = _normalized_enum(
                event.get("requirement_basis"), REQUIREMENT_BASES,
                {"preference": "user_preference", "project_constraint": "project_grounded"},
            )
            event["user_requirement_trigger"] = _normalized_enum(
                event.get("user_requirement_trigger"), USER_REQUIREMENT_TRIGGERS, {
                    "test_or_ci": "test_or_ci_feedback", "test_feedback": "test_or_ci_feedback",
                    "ci_feedback": "test_or_ci_feedback", "observed_output": "observed_output_feedback",
                    "output_feedback": "observed_output_feedback",
                    "repository": "repository_or_dependency_constraint",
                    "repository_constraint": "repository_or_dependency_constraint",
                    "dependency_constraint": "repository_or_dependency_constraint",
                    "agent_explanation": "agent_explanation_or_proposal",
                    "agent_proposal": "agent_explanation_or_proposal",
                    "review": "review_or_external_feedback",
                    "external_feedback": "review_or_external_feedback",
                    "spontaneous_revision": "spontaneous_user_revision",
                },
            )
            event["causal_link_strength"] = _normalized_enum(
                event.get("causal_link_strength"), CAUSAL_LINK_STRENGTHS,
                {"no_link": "none", "not_observable": "none"},
            )
            event["discovery_status"] = _normalized_enum(
                event.get("discovery_status"), DISCOVERY_STATUSES, {
                    "discoverable_later": "became_discoverable_later",
                    "not_discoverable": "not_discoverable_from_available_evidence",
                    "preference_when_articulated": "preference_only_when_articulated",
                },
            )
            event["implementation_status"] = _normalized_enum(
                event.get("implementation_status"), IMPLEMENTATION_STATUSES,
                {"complete": "satisfied", "completed": "satisfied", "failure": "failed"},
            )
            event["agent_response"] = _normalized_enum(
                event.get("agent_response"), AGENT_RESPONSES, {
                    "updated_after_new_evidence": "correctly_updated_after_new_evidence",
                    "symptom_patch": "surface_symptom_patch", "ignored": "ignored_new_evidence",
                    "unresolved": "unclear_or_unresolved", "unclear": "unclear_or_unresolved",
                },
            )
            for item in event.get("discovery_evidence_path", []):
                item["source"] = _normalized_enum(
                    item.get("source"), DISCOVERY_EVIDENCE_SOURCES, {
                        "test": "test_or_ci", "ci": "test_or_ci", "test_or_ci_feedback": "test_or_ci",
                        "observed_output_feedback": "observed_output", "user_feedback": "user_update",
                        "repo": "repository", "docs": "documentation", "assistant": "agent_inference",
                    },
                )
            # These are deterministic schema implications, not substantive reclassification.
            # user_requirement_trigger describes why a user articulated a requirement; it is N/A
            # when another source articulated the event.
            if event.get("articulation_source") != "user":
                event["user_requirement_trigger"] = "not_user_articulated"
                event["causal_link_strength"] = "none"
                event["trigger_turns"] = []
            elif event.get("user_requirement_trigger") in OBSERVATION_OR_FEEDBACK_TRIGGERS:
                if (event.get("causal_link_strength") in {"explicit", "strong"}
                        and not event.get("trigger_turns")):
                    event["causal_link_strength"] = "weak"
            elif event.get("user_requirement_trigger") in {"unclear", "not_user_articulated"}:
                event["causal_link_strength"] = "none"
                event["trigger_turns"] = []
            if event.get("material") is False:
                event["requirement_id"] = None
                event["earliest_discoverable_turn"] = None
                event["inferable_before_revelation"] = False
                event["discovery_status"] = "unclear"
                event["discovery_evidence_path"] = []
                event["agent_recognition_turn"] = None
                event["correct_implementation_turn"] = None
                event["implementation_status"] = "not_applicable"
                event["agent_response"] = "not_applicable"
                event["regressed_requirement_ids"] = []
                event["response_evidence_turns"] = []


def normalize_behavior_annotation(value: dict[str, Any]) -> None:
    for field in (
        "episode_in_scope", "project_reasoning_opportunity", "classification_evidence_sufficient",
        "important_uncertainty_identified", "instruction_scope_preserved", "project_evidence_used",
        "unstated_material_requirement_or_downstream_impact_identified",
        "material_plan_scope_strategy_or_acceptance_affected", "proactive_before_explicit_correction",
    ):
        if value.get(field) is None:
            value[field] = False
    for field in ("resolution_methods", "evidence"):
        if value.get(field) is None:
            value[field] = []
    if isinstance(value.get("resolution_methods"), list):
        aliases = {
            "targeted_user_question": "user_question", "clarification": "user_question",
            "repository_inspection": "repository_evidence", "repository": "repository_evidence",
            "test_or_ci": "execution_evidence", "execution_error": "execution_evidence",
            "observed_output": "execution_evidence", "prior_context": "prior_requirement",
            "compare_alternatives": "alternative_comparison",
        }
        value["resolution_methods"] = list(dict.fromkeys(
            _normalized_enum(method, RESOLUTION_METHODS, aliases)
            for method in value["resolution_methods"]
        ))


def derive_behavior_mode(value: dict[str, Any]) -> None:
    level2 = bool(value.get("important_uncertainty_identified")
                  and value.get("resolution_methods") and value.get("instruction_scope_preserved"))
    level3 = all((value.get("project_evidence_used"),
                  value.get("unstated_material_requirement_or_downstream_impact_identified"),
                  value.get("material_plan_scope_strategy_or_acceptance_affected")))
    if not value.get("episode_in_scope") or not value.get("classification_evidence_sufficient"):
        mode, level = "unclear", 0
    elif level3:
        mode, level = "project_level_requirement_discovery", 3
    elif level2:
        mode, level = "instruction_scoped_sensemaking", 2
    else:
        mode, level = "reactive_instruction_following", 1
    value["behavior_mode"], value["behavior_level"] = mode, level


def _valid_confidence(value: dict[str, Any]) -> None:
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("confidence must be numeric")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be in [0,1]")


def _valid_turn_list(value: Any, valid_turns: set[int], field: str) -> None:
    if not isinstance(value, list) or any(turn not in valid_turns for turn in value):
        raise ValueError(f"invalid {field}")


def validate_requirements_annotation(
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
        initial_turn = thread.get("initial_instruction_turn")
        if initial_turn not in valid_user_turns or initial_turn in initial_turns:
            raise ValueError("initial_instruction_turn must be a unique user turn")
        initial_turns.add(initial_turn)
        if not isinstance(thread.get("initial_requirements"), list):
            raise ValueError("initial_requirements must be a list")
        if not all(isinstance(thread.get(field), bool) for field in (
            "literal_initial_completion_satisfies_final_requirements", "evidence_sufficient")):
            raise ValueError("thread sufficiency flags must be boolean")

        final_requirements = thread.get("final_requirements")
        if not isinstance(final_requirements, list):
            raise ValueError("final_requirements must be a list")
        requirement_ids: set[str] = set()
        initially_present: set[str] = set()
        for req in final_requirements:
            requirement_id = req.get("requirement_id")
            if not isinstance(requirement_id, str) or not requirement_id or requirement_id in requirement_ids:
                raise ValueError("final requirement IDs must be unique non-empty strings")
            requirement_ids.add(requirement_id)
            if req.get("basis") not in REQUIREMENT_BASES:
                raise _invalid_enum("final_requirements[].basis", req.get("basis"), REQUIREMENT_BASES)
            if not isinstance(req.get("present_in_initial_instruction"), bool):
                raise ValueError("present_in_initial_instruction must be boolean")
            if req["present_in_initial_instruction"]:
                initially_present.add(requirement_id)
            _valid_turn_list(req.get("evidence_turns"), valid_turns, "final requirement evidence_turns")

        specificity = thread.get("initial_instruction_specificity")
        if not isinstance(specificity, dict) or specificity.get("score") not in {0, 1, 2, 3, 4}:
            raise ValueError("initial_instruction_specificity.score must be 0..4")
        explicit_ids, missing_ids = specificity.get("explicit_final_requirement_ids"), specificity.get("missing_final_requirement_ids")
        if not isinstance(explicit_ids, list) or not isinstance(missing_ids, list):
            raise ValueError("specificity requirement ID fields must be lists")
        if set(explicit_ids) != initially_present or set(missing_ids) != requirement_ids - initially_present:
            raise ValueError("specificity ID partition must match final requirements")

        events = thread.get("requirement_events")
        if not isinstance(events, list):
            raise ValueError("requirement_events must be a list")
        for event in events:
            if event.get("event_type") not in EVENT_TYPES:
                raise _invalid_enum("requirement_events[].event_type", event.get("event_type"), EVENT_TYPES)
            if event.get("articulation_source") not in ARTICULATION_SOURCES:
                raise _invalid_enum(
                    "requirement_events[].articulation_source",
                    event.get("articulation_source"), ARTICULATION_SOURCES,
                )
            if event.get("requirement_basis") not in REQUIREMENT_BASES:
                raise _invalid_enum(
                    "requirement_events[].requirement_basis",
                    event.get("requirement_basis"), REQUIREMENT_BASES,
                )
            if event.get("user_requirement_trigger") not in USER_REQUIREMENT_TRIGGERS:
                raise _invalid_enum(
                    "requirement_events[].user_requirement_trigger",
                    event.get("user_requirement_trigger"), USER_REQUIREMENT_TRIGGERS,
                )
            if event.get("causal_link_strength") not in CAUSAL_LINK_STRENGTHS:
                raise _invalid_enum(
                    "requirement_events[].causal_link_strength",
                    event.get("causal_link_strength"), CAUSAL_LINK_STRENGTHS,
                )
            if event.get("discovery_status") not in DISCOVERY_STATUSES:
                raise _invalid_enum(
                    "requirement_events[].discovery_status",
                    event.get("discovery_status"), DISCOVERY_STATUSES,
                )
            if event.get("implementation_status") not in IMPLEMENTATION_STATUSES:
                raise _invalid_enum(
                    "requirement_events[].implementation_status",
                    event.get("implementation_status"), IMPLEMENTATION_STATUSES,
                )
            if event.get("agent_response") not in AGENT_RESPONSES:
                raise _invalid_enum(
                    "requirement_events[].agent_response",
                    event.get("agent_response"), AGENT_RESPONSES,
                )
            if event.get("turn") not in valid_turns:
                raise ValueError(
                    f"requirement event turn={event.get('turn')!r} is absent from packet; "
                    f"valid_turns={sorted(valid_turns)}"
                )
            if not all(isinstance(event.get(field), bool) for field in
                       ("same_task", "material", "inferable_before_revelation")):
                raise ValueError("requirement event flags must be boolean")
            req_id = event.get("requirement_id")
            if event["same_task"] and event["material"] and req_id not in requirement_ids:
                raise ValueError("material same-task event must reference a final requirement")
            first_explicit = event.get("first_explicit_turn")
            if event["same_task"] and event["material"]:
                if first_explicit not in valid_turns:
                    raise ValueError(
                        f"material event first_explicit_turn={first_explicit!r} is absent from packet; "
                        f"valid_turns={sorted(valid_turns)}"
                    )
            elif first_explicit is not None and first_explicit not in valid_turns:
                raise ValueError(
                    f"non-material event first_explicit_turn={first_explicit!r} is absent from packet"
                )
            for field in ("basis_evidence_turns", "trigger_turns", "response_evidence_turns", "evidence_turns"):
                _valid_turn_list(event.get(field), valid_turns, field)
            for field in ("earliest_discoverable_turn", "agent_recognition_turn", "correct_implementation_turn"):
                if event.get(field) is not None and event[field] not in valid_turns:
                    raise ValueError(f"{field} is absent from packet")
            path = event.get("discovery_evidence_path")
            if not isinstance(path, list) or any(item.get("turn") not in valid_turns for item in path):
                raise ValueError("invalid discovery evidence path")
            for item in path:
                if item.get("source") not in DISCOVERY_EVIDENCE_SOURCES:
                    raise _invalid_enum(
                        "discovery_evidence_path[].source",
                        item.get("source"), DISCOVERY_EVIDENCE_SOURCES,
                    )
            earliest = event.get("earliest_discoverable_turn")
            if event["inferable_before_revelation"] != (
                earliest is not None and isinstance(first_explicit, int) and earliest < first_explicit
            ):
                raise ValueError("inferable_before_revelation conflicts with discovery turns")
            regressions = event.get("regressed_requirement_ids")
            if not isinstance(regressions, list) or not set(regressions) <= requirement_ids:
                raise ValueError("invalid regressed_requirement_ids")
            is_regression = event["agent_response"] == "satisfied_new_but_regressed_existing"
            if is_regression != bool(regressions):
                raise ValueError("regression response and IDs must agree")
            if event["articulation_source"] != "user":
                if (event["user_requirement_trigger"] != "not_user_articulated"
                        or event["causal_link_strength"] != "none" or event["trigger_turns"]):
                    raise ValueError(
                        "non-user-articulated event requires user_requirement_trigger="
                        "not_user_articulated, causal_link_strength=none, trigger_turns=[]"
                    )
            if event["user_requirement_trigger"] in OBSERVATION_OR_FEEDBACK_TRIGGERS:
                if event["causal_link_strength"] in {"explicit", "strong"} and not event["trigger_turns"]:
                    raise ValueError("observation-triggered event needs trigger_turns")
            elif (event["user_requirement_trigger"] in {"unclear", "not_user_articulated"}
                  and event["causal_link_strength"] != "none"):
                raise ValueError("unclear/not-user trigger requires causal_link_strength=none")
    _valid_confidence(value)


def validate_behavior_annotation(value: dict[str, Any], instruction_turn: int, valid_turns: set[int]) -> None:
    if value.get("instruction_turn") != instruction_turn:
        raise ValueError("judge returned the wrong instruction_turn")
    flags = (
        "episode_in_scope", "project_reasoning_opportunity", "classification_evidence_sufficient",
        "important_uncertainty_identified", "instruction_scope_preserved", "project_evidence_used",
        "unstated_material_requirement_or_downstream_impact_identified",
        "material_plan_scope_strategy_or_acceptance_affected", "proactive_before_explicit_correction",
    )
    if any(not isinstance(value.get(field), bool) for field in flags):
        raise ValueError("behavior atomic flags must be boolean")
    methods = value.get("resolution_methods")
    if not isinstance(methods, list):
        raise ValueError("invalid resolution_methods")
    invalid_methods = [method for method in methods if method not in RESOLUTION_METHODS]
    if invalid_methods:
        raise _invalid_enum("resolution_methods[]", invalid_methods[0], RESOLUTION_METHODS)
    evidence = value.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list")
    if value["episode_in_scope"] and value["classification_evidence_sufficient"] and not evidence:
        raise ValueError("classifiable episode must include evidence")
    if any(item.get("turn") not in valid_turns for item in evidence):
        raise ValueError("behavior evidence turn is absent from prefix")
    derive_behavior_mode(value)


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"estimate": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator}


def _numeric_summary(values: list[Any]) -> dict[str, Any]:
    clean = [float(v) for v in values if isinstance(v, (int, float))
             and not isinstance(v, bool) and isfinite(float(v))]
    return {"mean": mean(clean) if clean else None, "median": median(clean) if clean else None, "n": len(clean)}


def _comparison(exposed: list[Any], unexposed: list[Any]) -> dict[str, Any]:
    left, right = _numeric_summary(exposed), _numeric_summary(unexposed)
    return {
        "delayed_project_understanding": left,
        "no_delayed_project_understanding": right,
        "mean_difference_delayed_minus_not_delayed": (
            left["mean"] - right["mean"] if left["mean"] is not None and right["mean"] is not None else None
        ),
    }


def _timestamp_seconds(turn_timestamps: dict[str, Any], start: int, end: int) -> float | None:
    try:
        a = datetime.fromisoformat(str(turn_timestamps[str(start)]).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(turn_timestamps[str(end)]).replace("Z", "+00:00"))
        return max(0.0, (b - a).total_seconds())
    except (KeyError, TypeError, ValueError):
        return None


def _is_material_update(event: dict[str, Any], initial_turn: int) -> bool:
    return bool(event.get("same_task") is True and event.get("material") is True
                and event.get("event_type") in MATERIAL_EVENT_TYPES and event.get("turn") != initial_turn)


def _is_delayed(event: dict[str, Any], initial_turn: int) -> bool:
    return bool(_is_material_update(event, initial_turn)
                and event.get("requirement_basis") == "project_grounded"
                and event.get("inferable_before_revelation") is True
                and event.get("agent_response") not in {
                    "anticipated_and_satisfied", "proactive_question_then_satisfied"})


def aggregate_study1(requirement_rows: list[dict[str, Any]], behavior_rows: list[dict[str, Any]]) -> dict[str, Any]:
    records = [
        (row, thread) for row in requirement_rows if isinstance(row.get("annotation"), dict)
        for thread in row["annotation"].get("task_threads", []) if thread.get("evidence_sufficient") is True
    ]
    updates = [
        (row, thread, event) for row, thread in records
        for event in thread.get("requirement_events", [])
        if _is_material_update(event, thread.get("initial_instruction_turn"))
    ]
    user_updates = [x for x in updates if x[2].get("articulation_source") == "user"]
    basis_dist = Counter(x[2].get("requirement_basis", "unclear") for x in user_updates)
    grounded_user = [x for x in user_updates if x[2].get("requirement_basis") == "project_grounded"]
    late_grounded = [x for x in updates if x[2].get("requirement_basis") == "project_grounded"]
    earlier = [x for x in late_grounded if x[2].get("inferable_before_revelation") is True]
    discovery_status = Counter(x[2].get("discovery_status", "unclear") for x in late_grounded)
    discovery_sources: Counter[str] = Counter()
    for _, _, event in late_grounded:
        discovery_sources.update(item.get("source", "unclear") for item in event.get("discovery_evidence_path", []))

    final_count = sum(len(thread.get("final_requirements", [])) for _, thread in records)
    initial_count = sum(sum(req.get("present_in_initial_instruction") is True
                            for req in thread.get("final_requirements", [])) for _, thread in records)
    scores = [thread.get("initial_instruction_specificity", {}).get("score") for _, thread in records]
    responses = Counter(event.get("agent_response", "unclear_or_unresolved") for _, _, event in updates)
    grounded_responses = Counter(event.get("agent_response", "unclear_or_unresolved")
                                 for _, _, event in late_grounded)
    regression_updates = [x for x in updates if x[2].get("agent_response") == "satisfied_new_but_regressed_existing"]

    delayed_by_session: dict[str, bool] = {}
    regressions_by_session: Counter[str] = Counter()
    row_by_session: dict[str, dict[str, Any]] = {}
    for row, thread in records:
        sid = str(row.get("session_id"))
        row_by_session[sid] = row
        delayed_by_session.setdefault(sid, False)
        initial_turn = thread.get("initial_instruction_turn")
        for event in thread.get("requirement_events", []):
            delayed_by_session[sid] |= _is_delayed(event, initial_turn)
            if _is_material_update(event, initial_turn) and event.get("agent_response") == "satisfied_new_but_regressed_existing":
                regressions_by_session[sid] += 1

    comparisons: dict[str, Any] = {}
    for field in ("human_rework_lines", "linked_commit_deletions", "committed_agent_code_share", "turn_count",
                  "tool_call_count", "api_call_count", "total_tokens", "duration_seconds"):
        comparisons[field] = _comparison(
            [row_by_session[sid].get("observed_costs", {}).get(field)
             for sid, flag in delayed_by_session.items() if flag],
            [row_by_session[sid].get("observed_costs", {}).get(field)
             for sid, flag in delayed_by_session.items() if not flag],
        )
    comparisons["cross_requirement_regression_count"] = _comparison(
        [regressions_by_session[sid] for sid, flag in delayed_by_session.items() if flag],
        [regressions_by_session[sid] for sid, flag in delayed_by_session.items() if not flag],
    )

    delayed_events = [x for x in updates if _is_delayed(x[2], x[1].get("initial_instruction_turn"))]
    latency_turns: list[int] = []
    latency_seconds: list[float] = []
    unresolved = 0
    for row, _, event in delayed_events:
        start, end = event.get("earliest_discoverable_turn"), event.get("correct_implementation_turn")
        if isinstance(start, int) and isinstance(end, int) and end >= start:
            latency_turns.append(end - start)
            seconds = _timestamp_seconds(row.get("turn_timestamps", {}), start, end)
            if seconds is not None:
                latency_seconds.append(seconds)
        else:
            unresolved += 1

    episodes = [row["annotation"] for row in behavior_rows if isinstance(row.get("annotation"), dict)]
    opportunity = [ep for ep in episodes if ep.get("episode_in_scope") is True
                   and ep.get("project_reasoning_opportunity") is True
                   and ep.get("behavior_mode") in BEHAVIOR_MODES]
    behavior_dist = {mode: _rate(sum(ep.get("behavior_mode") == mode for ep in opportunity), len(opportunity))
                     for mode in BEHAVIOR_MODES}
    behavior_dist.update({
        "unit": "instruction_episode_with_project_reasoning_opportunity",
        "excluded_no_opportunity_count": sum(ep.get("episode_in_scope") is True
                                             and ep.get("project_reasoning_opportunity") is False for ep in episodes),
        "unclassified_count": sum(ep.get("episode_in_scope") is True
                                  and ep.get("project_reasoning_opportunity") is True
                                  and ep.get("behavior_mode") not in BEHAVIOR_MODES for ep in episodes),
    })
    material_threads = sum(any(_is_material_update(event, thread.get("initial_instruction_turn"))
                               for event in thread.get("requirement_events", [])) for _, thread in records)
    observation_triggered = [x for x in user_updates
                             if x[2].get("user_requirement_trigger") in OBSERVATION_OR_FEEDBACK_TRIGGERS
                             and x[2].get("causal_link_strength") in {"explicit", "strong"}]

    return {
        "initial_instruction_requirement_coverage": {
            **_rate(initial_count, final_count), "unit": "final_material_requirement",
            "specificity_score": _numeric_summary(scores),
        },
        "post_initial_material_update_basis": {
            "project_grounded_rate": {**_rate(len(grounded_user), len(user_updates)),
                                      "unit": "user_articulated_material_update"},
            "distribution": dict(sorted(basis_dist.items())),
        },
        "terminal_requirement_discovery": {
            "earlier_discoverable_rate": {**_rate(len(earlier), len(late_grounded)),
                                           "unit": "late_project_grounded_requirement_event"},
            "discovery_status_distribution": dict(sorted(discovery_status.items())),
            "evidence_path_source_distribution": dict(sorted(discovery_sources.items())),
        },
        "cost_of_delayed_project_understanding": {
            "exposure_definition": "late project-grounded material requirement was discoverable before articulation but neither anticipated nor elicited",
            "exposed_session_count": sum(delayed_by_session.values()),
            "unexposed_session_count": len(delayed_by_session) - sum(delayed_by_session.values()),
            "session_level_descriptive_comparisons": comparisons,
            "evidence_to_correct_implementation_latency": {
                "turns": _numeric_summary(latency_turns), "seconds": _numeric_summary(latency_seconds),
                "unresolved_or_unobservable_event_count": unresolved,
                "eligible_delayed_event_count": len(delayed_events),
            },
            "code_measurement_note": "human_rework_lines=human_modified+human_removed; linked_commit_deletions may cover multi-session checkpoints; committed_agent_code_share is an authorship-based survival proxy, not longitudinal line survival",
        },
        "agent_response_to_evolving_project_evidence": {
            "all_material_updates": dict(sorted(responses.items())),
            "late_project_grounded_updates": dict(sorted(grounded_responses.items())),
            "cross_requirement_regression_rate": {**_rate(len(regression_updates), len(updates)),
                                                   "unit": "material_requirement_update"},
        },
        "material_requirement_emergence_rate": {
            **_rate(material_threads, len(records)), "unit": "task_thread",
            "observation_or_feedback_triggered_event_rate": {
                **_rate(len(observation_triggered), len(user_updates)),
                "unit": "user_articulated_material_requirement_event",
            },
        },
        "literal_initial_instruction_satisfies_final_requirements_rate": {
            **_rate(sum(thread.get("literal_initial_completion_satisfies_final_requirements") is True
                        for _, thread in records), len(records)), "unit": "task_thread",
        },
        "behavior_level_distribution": behavior_dist,
    }
