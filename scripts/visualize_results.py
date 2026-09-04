#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# Keep plotting self-contained in restricted/container environments where the
# default user configuration directory may not be writable.
os.environ.setdefault("MPLCONFIGDIR", "/tmp/swe-chat-matplotlib")

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter


MODES = [
    ("direct_instruction_following", "Direct instruction following", "Execute without resolving important uncertainty", "#64748B"),
    ("instruction_scoped_sensemaking", "Instruction-scoped sensemaking", "Clarify with questions or evidence; goal stays fixed", "#3B82F6"),
    ("project_goal_inference", "Project-goal inference", "Infer an unstated material goal and change the target", "#10B981"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize the three Rubric-v4 behavior modes")
    parser.add_argument("--summary", default="outputs/judge20_v4_seed42/summary.json")
    parser.add_argument("--output", default="outputs/judge20_v4_seed42/behavior_modes.png")
    parser.add_argument(
        "--scope", choices=["opportunity", "overall"], default="opportunity",
        help="Use opportunity-conditioned episodes (recommended) or all valid episodes",
    )
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()

    payload = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    summary = payload["summary"]
    run = payload.get("run", {})
    scope_key = "opportunity_conditioned" if args.scope == "opportunity" else "overall"
    distribution = summary["behavior_mode_distribution"][scope_key]

    estimates = [float(distribution[key]["estimate"] or 0) for key, _, _, _ in MODES]
    counts = [int(distribution[key]["numerator"]) for key, _, _, _ in MODES]
    denominator = max(int(distribution[key]["denominator"]) for key, _, _, _ in MODES)

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 12,
        "axes.titleweight": "bold", "axes.edgecolor": "#CBD5E1",
    })
    fig, ax = plt.subplots(figsize=(12, 7.2), dpi=args.dpi)
    fig.patch.set_facecolor("#F8FAFC")
    ax.set_facecolor("#FFFFFF")
    y_positions = [2, 1, 0]

    # Full-width tracks make percentages immediately comparable.
    ax.barh(y_positions, [1, 1, 1], height=0.56, color="#EEF2F7", edgecolor="none")
    for y, estimate, count, (_, title, subtitle, color) in zip(y_positions, estimates, counts, MODES):
        ax.barh(y, estimate, height=0.56, color=color, edgecolor="none")
        ax.text(-0.025, y + 0.09, title, transform=ax.get_yaxis_transform(), ha="right", va="center", color="#0F172A", fontsize=13.5, fontweight="bold", clip_on=False)
        ax.text(-0.025, y - 0.13, subtitle, transform=ax.get_yaxis_transform(), ha="right", va="center", color="#64748B", fontsize=9.2, clip_on=False)
        if estimate >= 0.17:
            label_x, align, label_color = estimate - 0.018, "right", "white"
        else:
            label_x, align, label_color = estimate + 0.018, "left", "#0F172A"
        ax.text(label_x, y, f"{estimate:.1%}  ({count}/{denominator})", ha=align, va="center", color=label_color, fontsize=13, fontweight="bold")

    scope_title = "Episodes with a project-reasoning opportunity" if args.scope == "opportunity" else "All valid instruction episodes"
    ax.set_title("How Coding Agents Respond to Instructions", loc="left", pad=50, fontsize=23, color="#0F172A")
    ax.text(0, 2.72, scope_title, fontsize=13, color="#475569", ha="left")
    ax.text(0, 2.53, f"SWE-Chat pilot · {summary['n_valid']} sessions · Rubric v4 · model {run.get('model', 'unknown')}", fontsize=10.5, color="#64748B", ha="left")

    instruction_bound = estimates[0] + estimates[1]
    ax.text(
        0, -0.72,
        f"Instruction-bound behavior (Level 1 + Level 2): {instruction_bound:.1%}     "
        f"Project-goal inference (Level 3): {estimates[2]:.1%}",
        ha="left", va="center", fontsize=12.5, color="#0F172A", fontweight="bold",
        bbox={"boxstyle": "round,pad=0.65", "facecolor": "#F1F5F9", "edgecolor": "#CBD5E1"},
    )
    ax.text(
        0, -1.08,
        "Level 3 requires a proactive, evidence-supported inference of an unstated material goal that changes scope, strategy, or acceptance criteria.",
        ha="left", va="center", fontsize=9.5, color="#64748B",
    )

    ax.set_xlim(0, 1.08)
    ax.set_ylim(-1.3, 2.95)
    ax.set_yticks([])
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xticks([0, .25, .5, .75, 1.0])
    ax.grid(axis="x", color="#E2E8F0", linewidth=1)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.tick_params(axis="x", colors="#64748B")
    plt.subplots_adjust(left=.34, right=.96, top=.84, bottom=.16)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
