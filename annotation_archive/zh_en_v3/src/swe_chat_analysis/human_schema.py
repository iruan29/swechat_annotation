from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from . import study1, study2


STAGES = ("behavior", "requirements", "study2")
VERSIONS = {
    "behavior": study1.STUDY1_RUBRIC_VERSION,
    "requirements": study1.STUDY1_REQUIREMENTS_RUBRIC_VERSION,
    "study2": study2.STUDY2_RUBRIC_VERSION,
}
PROMPTS = {
    "behavior": study1.BEHAVIOR_SYSTEM_PROMPT,
    "requirements": study1.REQUIREMENTS_SYSTEM_PROMPT,
    "study2": study2.SYSTEM_PROMPT,
}
DERIVED = {
    "requirements": {"explicit_final_requirement_ids", "missing_final_requirement_ids", "inferable_before_revelation"},
    "behavior": set(),
    "study2": {"considered_user_belief_or_goal", "identified_instruction_reality_gap", "asked_targeted_clarification",
               "challenged_or_deviated_from_instruction", "followed_surface_instruction", "proactive_before_user_explained_mismatch"},
}
LABELS = {
    "task_threads": "任务线程（同一持续目标，不按每条纠正拆分）", "task_id": "线程 ID",
    "initial_instruction_turn": "该线程初始用户指令 T 编号", "instruction_turn": "本次指定指令 T 编号",
    "initial_requirements": "初始明确要求", "final_requirements": "最终重要要求",
    "initial_instruction_specificity": "初始要求完整度", "score": "完整度 0–4",
    "requirement_id": "要求 ID（线程内稳定，如 R1）", "requirement": "要求内容",
    "present_in_initial_instruction": "初始用户指令是否明确表达", "basis": "要求依据",
    "requirement_events": "要求变化或既有要求纠错事件", "requirement_change": "新要求、变化还是旧要求修复",
    "event_type": "事件类型", "articulation_source": "该事件由谁表达", "requirement_basis": "要求依据",
    "turn": "证据/事件 T 编号", "first_explicit_turn": "任何来源首次明确要求的时点",
    "first_user_requirement_turn": "用户首次明确表达（未表达则留空）", "proactive_question_turn": "主动针对性询问时点",
    "earliest_discoverable_turn": "最早可发现证据时点", "agent_recognition_turn": "识别实际要求的时点",
    "correct_implementation_turn": "正确实现得到证实的时点", "implementation_status": "实现状态",
    "discovery_status": "可发现性", "discovery_evidence_path": "发现证据路径（按时间顺序）",
    "agent_response": "对要求更新的响应", "regressed_requirement_ids": "被破坏的既有要求 ID",
    "evidence_sufficient": "最终要求与初始表达是否可识别（不是实现是否成功）",
    "evolution_evidence_sufficient": "要求演化历史是否充分", "implementation_evidence_sufficient": "实现验证证据是否充分",
    "literal_initial_completion_satisfies_final_requirements": "仅完成初始字面指令能否满足最终要求（允许未知）",
    "material": "是否实质改变可接受成果", "same_task": "是否属于同一任务",
    "user_requirement_trigger": "用户提出要求的触发来源", "causal_link_strength": "触发因果证据强度",
    "episode_in_scope": "是否为任务指令（非问候、状态通知）", "instruction_summary": "当前指令摘要",
    "project_reasoning_opportunity": "是否存在重要歧义、隐藏约束或下游影响", "opportunity_reason": "机会/无机会的依据",
    "classification_evidence_sufficient": "是否足以分类", "important_uncertainty_identified": "是否识别重要不确定性",
    "resolution_methods": "消解不确定性的方法", "instruction_scope_preserved": "是否保持已述任务范围",
    "project_evidence_used": "是否使用项目证据", "unstated_material_requirement_or_downstream_impact_identified": "是否发现未述重要要求/影响",
    "material_plan_scope_strategy_or_acceptance_affected": "是否实质改变计划、范围、策略或验收",
    "proactive_before_explicit_correction": "是否发生在用户明确纠正前", "requirement_novelty": "要求是否真正新颖",
    "novel_requirement": "具体未述要求（不能只是验证用户已提供的诊断）", "material_change": "因此发生的实质改变",
    "surface_instruction": "初始表面指令", "surface_instruction_turn": "初始表面指令的用户 T 编号",
    "user_belief_identifiable": "用户 belief 是否有证据可识别", "user_belief": "有证据支持的用户 belief",
    "actual_situation_identifiable": "实际项目情况是否可识别", "actual_project_situation": "实际项目情况",
    "material_instruction_reality_mismatch": "是否有重要 instruction–reality mismatch",
    "mismatch_types": "错位类型", "mismatch_discovery": "错位可发现性与证据路径",
    "initial_state_discoverability": "初始项目状态是否可发现", "earliest_mismatch_evidence_turn": "最早错位证据时点",
    "first_user_mismatch_explanation_turn": "用户首次明确解释错位的时点", "gap_driver": "belief 形成来源",
    "gap_driver_evidence_strength": "belief 来源证据强度", "belief_basis_scope": "belief 信息基础范围",
    "literal_counterfactual": "competent literal completion 反事实", "surface_instruction_satisfied": "字面指令是否能满足",
    "actual_situation_addressed": "实际项目情况是否能解决", "failure_caused_by_mismatch": "失败是否由错位而非实现能力导致",
    "agent_gap_response": "Agent 对错位的响应（时点派生分类）", "identified_instruction_uncertainty": "是否明确识别重要指令歧义",
    "mental_state_consideration_turn": "首次显式考虑用户潜在目标/belief 的时点", "reality_gap_detection_turn": "首次明确识别错位的时点",
    "clarification_turn": "针对性澄清时点", "resistance_turn": "有依据的挑战/改道时点",
    "surface_action_commitment_turn": "首次实质采纳/执行表面方案（不含诊断阅读）", "actual_situation_addressed_turn": "实际问题得到实质处理的时点",
    "detection_methods": "发现错位的方法", "observed_resolution_status": "最终观察到的解决情况",
    "confidence": "人工判断把握程度（0–1；不是校准概率）", "rationale": "判断理由/证据不足原因",
    "evidence": "证据（T 编号及摘录/转述）", "source": "证据来源", "speaker_or_source": "发言者/来源",
    "quote_or_paraphrase": "摘录或准确转述", "evidence_turns": "支持本判断的 T 编号",
    "basis_evidence_turns": "要求依据的 T 编号", "trigger_turns": "触发证据 T 编号",
    "response_evidence_turns": "响应与实现证据 T 编号", "novelty_evidence_turns": "本 episode 内发现新要求的非用户证据 T 编号",
    "belief_evidence": "用户 belief 证据", "actual_situation_evidence": "实际项目情况证据",
    "driver_evidence": "belief 来源证据", "mismatch_evidence_path": "错位证据路径（时间顺序）",
}


def _enums(stage: str, field: str, path: str) -> list[str] | None:
    common = {"requirement_basis": study1.REQUIREMENT_BASES, "basis": study1.REQUIREMENT_BASES,
              "event_type": study1.EVENT_TYPES, "articulation_source": study1.ARTICULATION_SOURCES,
              "requirement_change": study1.REQUIREMENT_CHANGES, "discovery_status": study1.DISCOVERY_STATUSES,
              "user_requirement_trigger": study1.USER_REQUIREMENT_TRIGGERS, "causal_link_strength": study1.CAUSAL_LINK_STRENGTHS,
              "implementation_status": study1.IMPLEMENTATION_STATUSES, "agent_response": study1.AGENT_RESPONSES,
              "resolution_methods": study1.RESOLUTION_METHODS, "requirement_novelty": study1.NOVELTY_STATUSES,
              "mismatch_types": study2.MISMATCH_TYPES, "gap_driver": study2.GAP_DRIVERS,
              "gap_driver_evidence_strength": study2.DRIVER_EVIDENCE_STRENGTHS, "belief_basis_scope": study2.BELIEF_BASIS_SCOPES,
              "initial_state_discoverability": study2.INITIAL_DISCOVERABILITY_STATUSES,
              "detection_methods": study2.AGENT_DETECTION_METHODS, "observed_resolution_status": study2.RESOLUTION_STATUSES}
    if field == "source":
        choices = study1.DISCOVERY_EVIDENCE_SOURCES if stage == "requirements" else (
            study2.BELIEF_EVIDENCE_SOURCES if "belief_evidence" in path else
            study2.ACTUAL_SITUATION_EVIDENCE_SOURCES if "actual_situation_evidence" in path else study2.MISMATCH_DISCOVERY_SOURCES)
        return sorted(choices)
    return sorted(common[field]) if field in common else None


def schema(stage: str) -> dict[str, Any]:
    tail = PROMPTS[stage].split("Return exactly one JSON object:", 1)[1].lstrip()
    exemplar, _ = json.JSONDecoder().raw_decode(tail)

    def build(value: Any, field: str = "", path: str = "") -> dict[str, Any]:
        node: dict[str, Any] = {"label": LABELS.get(field, field), "field": field}
        if isinstance(value, dict):
            node.update(type="object", properties={key: build(item, key, path + "." + key)
                                                   for key, item in value.items() if key not in DERIVED[stage]})
        elif isinstance(value, list):
            example = value[0] if value else (0 if field.endswith("turns") else "")
            node.update(type="array", items=build(example, field, path))
        elif isinstance(value, bool):
            node.update(type="boolean", nullable=field == "literal_initial_completion_satisfies_final_requirements")
        elif isinstance(value, (int, float)) or field.endswith("_turn") or field == "turn":
            node.update(type="number" if field == "confidence" else "integer", nullable=field.endswith("_turn") and field not in {"instruction_turn", "initial_instruction_turn", "surface_instruction_turn"})
        else:
            node.update(type="string")
        choices = _enums(stage, field, path)
        if choices and node["type"] != "array":
            node["enum"] = choices
        return node

    return build(exemplar)


def blank(node: dict[str, Any]) -> Any:
    if node.get("nullable"):
        return None
    kind = node["type"]
    if kind == "object":
        return {key: blank(child) for key, child in node["properties"].items()}
    if kind == "array":
        return []
    if kind in {"integer", "number", "boolean"}:
        return None
    return ""


def check_answers(node: dict[str, Any], value: Any, path: str = "") -> None:
    kind = node["type"]
    if kind == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path}: 必须是对象")
        for key, child in node["properties"].items():
            check_answers(child, value.get(key), path + "." + key)
    elif kind == "array":
        if not isinstance(value, list) or len(value) > 500:
            raise ValueError(f"{path}: 必须是数组，最多 500 项")
        for index, item in enumerate(value):
            check_answers(node["items"], item, f"{path}[{index}]")
    elif value is None and node.get("nullable"):
        return
    elif kind == "boolean" and type(value) is not bool:
        raise ValueError(f"{path}: 请选择是或否，未回答不会自动视为否")
    elif kind in {"integer", "number"} and (type(value) not in {int, float} or kind == "integer" and type(value) is not int):
        raise ValueError(f"{path}: 请填写数值")
    elif kind == "string" and not isinstance(value, str):
        raise ValueError(f"{path}: 请填写文本")
    if kind == "string" and node.get("field") in {"requirement", "surface_instruction", "instruction_summary", "rationale", "evidence", "quote_or_paraphrase", "task_id", "requirement_id"} and not value.strip():
        raise ValueError(f"{path}: 请填写具体内容或证据不足的原因")
    if "enum" in node and value not in node["enum"]:
        raise ValueError(f"{path}: 请选择合法类别")


def validate(stage: str, raw: dict[str, Any], events: list[dict[str, Any]], target: int) -> dict[str, Any]:
    value = deepcopy(raw)
    if stage == "study2":
        for thread in value.get("task_threads", []):
            if not isinstance(thread, dict):
                raise ValueError("任务线程必须是对象")
            if thread.get("actual_situation_identifiable") is False:
                thread["actual_project_situation"] = ""
                thread["actual_situation_evidence"] = []
                study2._normalize_no_mismatch_fields(thread, "unclear")
            elif thread.get("material_instruction_reality_mismatch") is False:
                study2._normalize_no_mismatch_fields(thread, "no_material_mismatch")
            if thread.get("user_belief_identifiable") is False:
                thread["user_belief"] = ""
                thread["belief_evidence"] = []
                if thread.get("material_instruction_reality_mismatch") is True:
                    thread.update(gap_driver="unclear", gap_driver_evidence_strength="insufficient",
                                  belief_basis_scope="unclear", driver_evidence=[])
    check_answers(schema(stage), value)
    turns = {event["turn"] for event in events}
    user_turns = {event["turn"] for event in events if event["kind"] == "user_prompt"}
    if stage == "behavior":
        study1.normalize_behavior_annotation(value)
        study1.validate_behavior_annotation(value, target, turns)
    elif stage == "requirements":
        study1.normalize_requirements_annotation(value)
        study1.validate_requirements_annotation(value, turns, user_turns)
    else:
        study2.normalize_annotation(value)
        study2.validate_annotation(value, turns, user_turns)
    return value
