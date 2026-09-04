from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MODES = (
    "direct_instruction_following",
    "instruction_scoped_sensemaking",
    "project_goal_inference",
)


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "estimate": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid_rows = [row for row in rows if isinstance(row.get("annotation"), dict)]

    evolved = sum(
        bool(row["annotation"]["material_evolution"]["changed"])
        for row in valid_rows
    )
    literal_satisfies = sum(
        bool(
            row["annotation"]["initial_instruction_sufficiency"]
            ["would_literal_completion_satisfy_final_requirements"]
        )
        for row in valid_rows
    )

    all_episodes = [
        episode
        for row in valid_rows
        for episode in row["annotation"]["behavior_episodes"]
    ]
    classified_episodes = [
        episode for episode in all_episodes
        if episode.get("response_mode") in MODES
    ]
    level_distribution = {
        mode: _rate(
            sum(episode["response_mode"] == mode for episode in classified_episodes),
            len(classified_episodes),
        )
        for mode in MODES
    }
    level_distribution["unclassified_count"] = (
        len(all_episodes) - len(classified_episodes)
    )

    return {
        "requirement_evolution_rate": _rate(evolved, len(valid_rows)),
        "literal_initial_instruction_satisfies_all_final_requirements_rate": _rate(
            literal_satisfies, len(valid_rows)
        ),
        "behavior_level_distribution": level_distribution,
    }


def save_summary(
    output_dir: Path, summary: dict[str, Any], run_meta: dict[str, Any]
) -> None:
    del run_meta
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
