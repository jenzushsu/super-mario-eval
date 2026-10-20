"""Render publication figures from results.csv, without API calls or emulator use.

uv run --no-project --with matplotlib==3.10.8 python docs/blog/zoom-decisions-mario/render_charts.py
"""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent
ROWS = list(csv.DictReader((ROOT / "results.csv").open()))
COLORS = {"jev-1.13.0": "#687789", "zoom-decisions": "#1769AA", "zoom-decisions-pro": "#007F78"}
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.edgecolor": "#CBD5E1",
        "text.color": "#162638",
        "axes.labelcolor": "#334155",
        "xtick.color": "#475569",
        "ytick.color": "#334155",
        "svg.fonttype": "none",
        "savefig.facecolor": "white",
    }
)


def row(pairing, depth, model):
    matches = [
        r
        for r in ROWS
        if r["pairing"] == pairing and int(r["depth"]) == depth and r["model"] == model
    ]
    assert len(matches) == 1
    return matches[0]


def style(ax):
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#E7ECF1", linewidth=0.8)
    ax.tick_params(axis="y", length=0, pad=8)


def save(fig, name):
    for ext in ("png", "svg"):
        fig.savefig(ROOT / "assets" / f"{name}.{ext}", dpi=180)
    plt.close(fig)


fig, axes = plt.subplots(1, 2, figsize=(12, 6.6))
fig.subplots_adjust(left=0.14, right=0.96, top=0.76, bottom=0.23, wspace=0.55)
fig.text(0.06, 0.94, "Both Zoom models cleared every final episode", fontsize=21, weight="bold")
fig.text(
    0.06,
    0.88,
    "Stage 1-1 • v7 • 10 episodes per model in each pairing • survival guard off",
    fontsize=11,
)
for ax, pairing, label in zip(
    axes, ("zoom-decisions", "zoom-decisions-pro"), ("Decisions", "Decisions Pro")
):
    selected = [row(pairing, depth, model) for depth in (1, 2) for model in ("jev-1.13.0", pairing)]
    ypos = [3.6, 2.6, 1, 0]
    rates = [100 * int(r["clears"]) / int(r["episodes"]) for r in selected]
    ax.barh(ypos, rates, height=0.65, color=[COLORS[r["model"]] for r in selected])
    ax.set_yticks(
        ypos,
        [f"{'Jev' if r['model'] == 'jev-1.13.0' else label}\nDepth {r['depth']}" for r in selected],
    )
    for y, rate, r in zip(ypos, rates, selected):
        ax.text(
            rate + 2, y, f"{r['clears']}/{r['episodes']}", va="center", fontsize=11, weight="bold"
        )
    ax.set_xlim(0, 116)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("Observed stage-clear rate", labelpad=12)
    ax.set_title(f"Jev vs {label}", loc="left", fontsize=14, pad=15, weight="bold")
    style(ax)
fig.text(
    0.06,
    0.105,
    "Jev batches are shown separately. The 9/10 batch had one stall; no model-controlled deaths or API failures.",
    fontsize=10,
)
fig.text(
    0.06,
    0.065,
    "Repeated development-stage runs; these results do not establish generalization or a guaranteed success rate.",
    fontsize=10,
    color="#64748B",
)
save(fig, "clear-rates")

selected = [
    row(model, depth, model)
    for model in ("zoom-decisions", "zoom-decisions-pro")
    for depth in (1, 2)
]
labels = [
    f"{'Decisions' if r['model'] == 'zoom-decisions' else 'Decisions Pro'} · depth {r['depth']}"
    for r in selected
]
fig, axes = plt.subplots(1, 2, figsize=(12, 6.6))
fig.subplots_adjust(left=0.20, right=0.96, top=0.76, bottom=0.31, wspace=0.18)
fig.text(0.06, 0.94, "Fewer decisions, substantially more simulation", fontsize=21, weight="bold")
fig.text(
    0.06,
    0.88,
    "Zoom gameplay means per episode • each configuration cleared 10/10 • survival guard off",
    fontsize=11,
)
for ax, key, title in zip(
    axes, ("mean_decisions", "mean_simulation_frames"), ("Model decisions", "Simulation frames")
):
    vals = [float(r[key]) for r in selected]
    ax.barh(range(4), vals, height=0.6, color=[COLORS[r["model"]] for r in selected])
    ax.invert_yaxis()
    ax.set_yticks(range(4), labels if ax is axes[0] else [""] * 4)
    ax.set_title(title, loc="left", fontsize=14, weight="bold", pad=15)
    ax.set_xlabel("Average per episode", labelpad=12)
    ax.set_xlim(0, 40 if key == "mean_decisions" else 530000)
    if key == "mean_simulation_frames":
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x / 1000:.0f}k"))
    for y, v in enumerate(vals):
        text = f"{v:.1f}" if key == "mean_decisions" else f"{v:,.0f}"
        ax.text(
            v + (0.6 if key == "mean_decisions" else 7000),
            y,
            text,
            va="center",
            fontsize=11,
            weight="bold",
        )
    style(ax)
for i, (name, model) in enumerate(
    (("Decisions", "zoom-decisions"), ("Decisions Pro", "zoom-decisions-pro"))
):
    a, b = row(model, 1, model), row(model, 2, model)
    reduction = 100 * (1 - float(b["mean_decisions"]) / float(a["mean_decisions"]))
    ratio = float(b["mean_simulation_frames"]) / float(a["mean_simulation_frames"])
    fig.text(
        0.06,
        0.16 - i * 0.045,
        f"{name}: depth 2 used {reduction:.1f}% fewer decisions and {ratio:.1f}× the simulation frames.",
        fontsize=11,
    )
fig.text(
    0.06,
    0.055,
    "Simulation frames measure emulator work, not API tokens or monetary cost. Both axes start at zero.",
    fontsize=10,
    color="#64748B",
)
save(fig, "lookahead-tradeoff")
print("Rendered clear-rates and lookahead-tradeoff as PNG and SVG.")
