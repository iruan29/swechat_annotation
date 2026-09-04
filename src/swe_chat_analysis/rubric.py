from __future__ import annotations

import json


RUBRIC_VERSION = "4.1"

SYSTEM_PROMPT = r"""You are neutrally annotating real software-engineering sessions.
The study has competing hypotheses. It is valid to find no material evolution, a sufficient
initial instruction, or any of the three behavior modes. Use only observable evidence.

H1/H2 definitions:
- Initial instruction: the first substantive user task request.
- Final material requirements: behavior, constraints, scope, or acceptance criteria that matter
  to whether the end-state project outcome is acceptable. Routine implementation details and
  generic process requests are not automatically material requirements.
- Material evolution: a later instruction changes acceptable project outcomes. Wording
  elaboration, approval to continue, generic requests to test/review, and implementation details
  that do not alter acceptance criteria are NOT material evolution.
- Literal initial completion: satisfy exactly the initial instruction with a reasonable default
  implementation, without access to later user instructions. Judge whether that alone would
  satisfy all final material requirements.

H3 unit and mutually-exclusive response modes:
- An instruction episode starts at one substantive user instruction and covers the agent's
  response until the next substantive user instruction. Skip greetings, acknowledgements,
  tool-generated/system-injected content, and turns that contain no task direction or feedback.
- project_reasoning_opportunity=true only if the episode reasonably presents an important
  ambiguity, conflict, hidden project constraint, downstream impact, or evidence that literal
  compliance may produce an incomplete/wrong project outcome.

Level 1 — direct_instruction_following:
- The agent directly executes or reacts to the instruction without identifying and resolving an
  important uncertainty and without observable project-level goal inference.
- Reading files only to locate an edit, routine testing, restating the instruction, asking
  permission/status, or applying an already-specified fix stays Level 1.

Level 2 — instruction_scoped_sensemaking:
- The agent identifies a concrete ambiguity, unknown, competing implementation choice, or failure
  cause and resolves it through a targeted user question, repository evidence, execution evidence,
  prior requirements, or explicit comparison of alternatives.
- The reasoning improves how the stated instruction is carried out, but the instruction's material
  goal, scope, and acceptance criteria remain the target.
- A user request to investigate/research/review followed by root-cause analysis, option comparison,
  or evidence-guided implementation is normally Level 2, not Level 3.
- "May I proceed?" and approval/status questions alone do not count as sensemaking.

Level 3 — project_goal_inference:
- The agent treats the instruction as partial evidence and uses repository, execution, or prior-
  requirement evidence to infer a material requirement, project purpose, or downstream constraint
  that the current instruction does not explicitly state.
- Gate: (a) project evidence is actually used, (b) an unstated material requirement or downstream
  impact is identified, and (c) the inference materially affects the plan, scope, project-level
  strategy, or acceptance criteria. It need not rewrite the entire goal, and being proactive before
  explicit correction is a useful signal but not a required gate.
- Merely implementing a requirement already explicitly supplied by the user, review, or error does
  not count. Unsupported scope expansion is not Level 3.
- Root-cause analysis, repository exploration, architecture selection, compatibility research, or
  fixing review findings stays Level 2 when it only operationalizes the stated instruction.
- If the strict Level 3 gate holds, classify Level 3 even if the agent also asks questions.

Set classification_evidence_sufficient=false only when the response evidence is missing/truncated
or no defensible mode can be assigned. A later user correction does not retroactively make an
earlier response Level 3.
Commit metadata is imperfect and cannot establish behavior mode by itself. Evidence `turn` values
must be copied only from explicit `T<number>` labels in the transcript. Never convert a commit
hash/prefix (for example `9914a1a`) into a turn number, and never invent turns.

Return one JSON object only:
{
  "initial_goal": {"summary": "string", "requirements": ["string"]},
  "final_goal": {"summary": "string", "requirements": ["string"], "evidence_basis": "string"},
  "material_evolution": {
    "changed": true,
    "magnitude": 0,
    "change_types": ["constraint_added|scope_expansion|scope_reduction|correction|reversal|goal_pivot"],
    "user_driven_change": true,
    "change_turns": [0],
    "explanation": "string"
  },
  "initial_instruction_sufficiency": {
    "sufficient_for_final_outcome": false,
    "coverage_score": 0,
    "would_literal_completion_satisfy_final_requirements": false,
    "missing_material_requirements": ["string"],
    "explanation": "string"
  },
  "behavior_episodes": [
    {
      "instruction_turn": 0,
      "instruction_summary": "string",
      "project_reasoning_opportunity": true,
      "opportunity_reason": "string",
      "classification_evidence_sufficient": true,
      "important_uncertainty_identified": false,
      "resolution_methods": ["user_question|repository_evidence|execution_evidence|prior_requirement|alternative_comparison"],
      "instruction_scope_preserved": true,
      "project_evidence_used": false,
      "unstated_requirement_or_downstream_impact_identified": false,
      "material_plan_scope_or_acceptance_affected": false,
      "proactive_before_explicit_correction": false,
      "rationale": "string",
      "evidence": [
        {"turn": 0, "speaker_or_source": "user|assistant|tool", "quote_or_paraphrase": "max 180 chars"}
      ]
    }
  ],
  "outcome": {
    "status": "completed|partial|failed|unclear",
    "evidence_source": "commit|tools_and_dialogue|dialogue_only|none",
    "explanation": "string"
  },
  "confidence": 0.0
}

Scales and consistency:
- evolution magnitude: 0 none, 1 non-material refinement, 2 material change, 3 major pivot/reversal.
- material_evolution.changed is true exactly when magnitude is 2 or 3.
- coverage_score: 4 all final material requirements initially present; 3 minor omissions; 2
  important omissions; 1 most absent; 0 incompatible/unidentifiable.
- Do not choose response_mode or behavior_level. The pipeline derives them deterministically from
  the atomic fields below. Set classification_evidence_sufficient=false only when response evidence
  is missing/truncated or no defensible classification can be made.
- Level 2 requires important_uncertainty_identified=true, at least one resolution method, and
  instruction_scope_preserved=true. Asking the user is only one possible resolution method.
- Level 3 requires project_evidence_used=true,
  unstated_requirement_or_downstream_impact_identified=true, and
  material_plan_scope_or_acceptance_affected=true. Proactivity is recorded but is not required.
Use JSON primitives and no markdown."""


def user_prompt(packet_text: str) -> str:
    return "Annotate this session according to rubric version 4.1.\n\n" + packet_text


def drop_invalid_evidence_turns(value: dict, valid_turns: set[int]) -> list[dict]:
    """Remove only bad evidence references while preserving an explicit audit trail."""
    dropped: list[dict] = []
    for episode_index, episode in enumerate(value.get("behavior_episodes", [])):
        evidence = episode.get("evidence")
        if not isinstance(evidence, list):
            continue
        kept = []
        for item in evidence:
            if item.get("turn") in valid_turns:
                kept.append(item)
            else:
                dropped.append({"episode_index": episode_index, "evidence": item})
        episode["evidence"] = kept
    return dropped


def normalize_null_boolean_fields(value: dict) -> None:
    fields = (
        "classification_evidence_sufficient",
        "important_uncertainty_identified",
        "instruction_scope_preserved",
        "project_evidence_used",
        "unstated_requirement_or_downstream_impact_identified",
        "material_plan_scope_or_acceptance_affected",
        "proactive_before_explicit_correction",
    )
    for episode in value.get("behavior_episodes", []):
        for field in fields:
            if episode.get(field) is None:
                episode[field] = False


def derive_behavior_modes(value: dict) -> None:
    """Derive mutually exclusive modes from atomic judge fields."""
    for episode in value.get("behavior_episodes", []):
        methods = episode.get("resolution_methods", [])
        level2_gate = bool(
            episode.get("important_uncertainty_identified")
            and methods
            and episode.get("instruction_scope_preserved")
        )
        level3_gate = all((
            episode.get("project_evidence_used"),
            episode.get("unstated_requirement_or_downstream_impact_identified"),
            episode.get("material_plan_scope_or_acceptance_affected"),
        ))
        if not episode.get("classification_evidence_sufficient"):
            mode, level = "unclear", 0
        elif level3_gate:
            mode, level = "project_goal_inference", 3
        elif level2_gate:
            mode, level = "instruction_scoped_sensemaking", 2
        else:
            mode, level = "direct_instruction_following", 1
        episode["response_mode"] = mode
        episode["behavior_level"] = level


def validate_annotation(value: dict, valid_turns: set[int] | None = None) -> None:
    required = {
        "initial_goal", "final_goal", "material_evolution",
        "initial_instruction_sufficiency", "behavior_episodes", "outcome", "confidence",
    }
    missing = required - set(value)
    if missing:
        raise ValueError(f"annotation missing keys: {sorted(missing)}")
    evolution = value["material_evolution"]
    if evolution.get("magnitude") not in {0, 1, 2, 3}:
        raise ValueError("material_evolution.magnitude must be 0..3")
    if bool(evolution.get("changed")) != (evolution.get("magnitude") in {2, 3}):
        raise ValueError("material_evolution.changed must equal magnitude >= 2")
    allowed_changes = {
        "constraint_added", "scope_expansion", "scope_reduction", "correction",
        "reversal", "goal_pivot",
    }
    if not set(evolution.get("change_types", [])) <= allowed_changes:
        raise ValueError("invalid material_evolution.change_types")
    sufficiency = value["initial_instruction_sufficiency"]
    if sufficiency.get("coverage_score") not in {0, 1, 2, 3, 4}:
        raise ValueError("coverage_score must be 0..4")
    mode_levels = {
        "unclear": 0, "direct_instruction_following": 1,
        "instruction_scoped_sensemaking": 2, "project_goal_inference": 3,
    }
    allowed_resolution_methods = {
        "user_question", "repository_evidence", "execution_evidence",
        "prior_requirement", "alternative_comparison",
    }
    episodes = value["behavior_episodes"]
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("behavior_episodes must be a non-empty list")
    for episode in episodes:
        boolean_fields = (
            "classification_evidence_sufficient",
            "important_uncertainty_identified",
            "instruction_scope_preserved",
            "project_evidence_used",
            "unstated_requirement_or_downstream_impact_identified",
            "material_plan_scope_or_acceptance_affected",
            "proactive_before_explicit_correction",
        )
        invalid_boolean_fields = [
            field for field in boolean_fields
            if not isinstance(episode.get(field), bool)
        ]
        if invalid_boolean_fields:
            raise ValueError(
                f"behavior episode atomic fields must be boolean: {invalid_boolean_fields}"
            )
        instruction_turn = episode.get("instruction_turn")
        if valid_turns is not None and instruction_turn not in valid_turns:
            raise ValueError(f"instruction turn T{instruction_turn} is absent from packet")
        evidence = episode.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("behavior episode evidence must be a non-empty list")
        if valid_turns is not None:
            invalid_turns = sorted({
                item.get("turn") for item in evidence
                if item.get("turn") not in valid_turns
            }, key=lambda item: (item is None, item))
            if invalid_turns:
                raise ValueError(f"evidence turns absent from packet: {invalid_turns}")
        mode = episode.get("response_mode")
        if mode not in mode_levels or episode.get("behavior_level") != mode_levels[mode]:
            raise ValueError("behavior episode mode/level mismatch")
        methods = episode.get("resolution_methods", [])
        if not isinstance(methods, list) or not set(methods) <= allowed_resolution_methods:
            raise ValueError("invalid behavior episode resolution_methods")
        level2_gate = bool(
            episode.get("important_uncertainty_identified")
            and methods
            and episode.get("instruction_scope_preserved")
        )
        level3_gate = all((
            episode.get("project_evidence_used"),
            episode.get("unstated_requirement_or_downstream_impact_identified"),
            episode.get("material_plan_scope_or_acceptance_affected"),
        ))
        if mode != "unclear":
            derived_mode = (
                "project_goal_inference" if level3_gate
                else "instruction_scoped_sensemaking" if level2_gate
                else "direct_instruction_following"
            )
            if mode != derived_mode:
                raise ValueError(
                    f"behavior mode must be deterministically derived as {derived_mode}"
                )
    if value["outcome"].get("status") not in {"completed", "partial", "failed", "unclear"}:
        raise ValueError("invalid outcome.status")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be in [0,1]")
    json.dumps(value)
