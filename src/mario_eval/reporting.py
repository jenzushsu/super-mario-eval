from __future__ import annotations

import importlib.metadata
import json
import math
import platform
import statistics
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .rankers import PROMPT_VERSION
from .simulation import ACTION_SET

SCHEMA = "mario-eval-assisted-v1"


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def provenance():
    root = Path(__file__).resolve().parents[2]

    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None

    packages = {}
    for package in ("gym-super-mario-bros", "nes-py", "gymnasium", "numpy", "typesafe-sdk"):
        packages[package] = importlib.metadata.version(package)
    return {
        "schema": SCHEMA,
        "application_commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "python": platform.python_version(),
        "dependencies": packages,
        "action_set": ACTION_SET,
        "prompt_version": PROMPT_VERSION,
        "reference": "4esv/jev-mario@8459bbb476c73463d9d3389639c158ecca4e21b4 (methodology only)",
    }


def new_run(root, config):
    path = Path(root) / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    path.mkdir(parents=True)
    write_json(path / "config.json", provenance() | config | {"run_id": path.name})
    return path


class Journal:
    def __init__(self, path):
        self.lock = Lock()
        self.handle = Path(path).open("w", encoding="utf-8")  # noqa: SIM115 — explicitly closed with episode lifecycle

    def emit(self, event, **values):
        with self.lock:
            self.handle.write(
                json.dumps({"schema": SCHEMA, "event": event, **values}, allow_nan=False) + "\n"
            )
            self.handle.flush()

    def close(self):
        self.handle.close()


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def report(path, rows, track, offline, shared_validation=None):
    aggregate = []
    for policy in dict.fromkeys(row["policy"] for row in rows):
        selected = [row for row in rows if row["policy"] == policy]
        latencies = [v for row in selected for v in row.get("latencies_ms", [])]
        aggregate.append(
            {
                "policy": policy,
                "samples": len(selected),
                "outcomes": dict(Counter(row["reason"] for row in selected)),
                "median_best_x": statistics.median(row["best_x"] for row in selected),
                "api_attempts": sum(row["api_attempts"] for row in selected),
                "latency_p50_ms": statistics.median(latencies) if latencies else None,
                "latency_p95_ms": percentile(latencies, 0.95),
                "simulation_frames": sum(row["simulation_frames"] for row in selected),
                "wall_seconds": sum(row["wall_seconds"] for row in selected),
                "cost_usd": None,
                "diagnostics": dict(
                    sum((Counter(row.get("diagnostics", {})) for row in selected), Counter())
                ),
            }
        )
    for item in aggregate:
        ages = [
            age
            for row in rows
            if row["policy"] == item["policy"]
            for age in row.get("decision_age_frames", [])
        ]
        item["decision_age_p50_frames"] = statistics.median(ages) if ages else None
        item["decision_age_max_frames"] = max(ages) if ages else None
    write_json(
        path / "summary.json",
        {
            "schema": SCHEMA,
            "track": track,
            "offline": offline,
            "survival_guard": any(row.get("survival_guard", False) for row in rows),
            "aggregate": aggregate,
            "shared_validation": shared_validation,
            "runs": rows,
        },
    )
    lines = [
        "# Assisted Mario comparison",
        "",
        f"Track: **{track}**. "
        + (
            "**OFFLINE fixtures — no live model results.**"
            if offline
            else "Live provider evaluation; failures remain in the results."
        ),
        "",
        "The emulator supplies finite-horizon outcomes. This measures assisted ranking, not unaided control.",
        "",
        "| Policy | Samples | Outcomes | Median best x | API attempts | Median / p95 latency (ms) |",
        "|---|---:|---|---:|---:|---|",
    ]
    if track == "identical_states":
        lines = [line.replace("Median best x", "Median checkpoint x") for line in lines]
    for item in aggregate:
        latency = (
            "n/a"
            if item["latency_p50_ms"] is None
            else f"{item['latency_p50_ms']:.1f} / {item['latency_p95_ms']:.1f}"
        )
        outcomes = ", ".join(f"{k}: {v}" for k, v in item["outcomes"].items())
        lines.append(
            f"| {item['policy']} | {item['samples']} | {outcomes} | {item['median_best_x']} | {item['api_attempts']} | {latency} |"
        )
    if shared_validation is not None:
        lines += [
            "",
            (
                f"Shared corpus validation: {shared_validation['simulation_frames']} simulation frames, "
                f"{shared_validation['wall_seconds']:.2f} wall seconds (counted once, separate from policy rows)."
            ),
        ]
    lines += [
        "",
        "## Individual runs",
        "",
        "| Policy / attempt | End reason | Decisions | Game frames / seconds | Simulation frames | Wall seconds |",
        "|---|---|---:|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['policy']} / {row['attempt']} | {row['reason']} | {row['decisions']} | {row['game_frames']} / {row['game_frames'] / 60:.2f} | {row['simulation_frames']} | {row['wall_seconds']:.2f} |"
        )
    lines += [
        "",
        "## Decision diagnostics",
        "",
        "Counts describe original model/policy selections, before any survival guard; not observed future deaths or model accuracy.",
        "",
        "| Policy | Immediate death | All tested follow-ups fatal | Unknown outcome | Incomplete follow-ups | Non-forward | Repeated no progress | Guard overrides |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in aggregate:
        d = item["diagnostics"]
        values = [
            d.get(key, 0)
            for key in (
                "immediate_death",
                "all_tested_followups_fatal",
                "unknown_outcome",
                "incomplete_followup_coverage",
                "zero_progress",
                "repeated_no_progress",
                "survival_guard_overrides",
            )
        ]
        lines.append(f"| {item['policy']} | " + " | ".join(map(str, values)) + " |")
    lines += [
        "",
        "Repeated no progress means selecting nonpositive displacement after at least one horizon without a new best x. Retreats can trigger it; it is not an automatic override.",
        "Complete follow-up coverage tests all seven moves for one horizon only; it does not prove eventual safety. Depth zero is explicitly untested.",
    ]
    if any(row.get("survival_guard", False) for row in rows):
        lines += [
            "",
            "**Survival guard enabled for every lane.** These results measure providers plus a shared guard, not raw provider choices. Original rankings and each guard decision are logged separately; execution records identify replacements. The guard does not guarantee a clear or prevent stalls.",
        ]
    lines += [
        "",
        "## Interpretation",
        "",
        "- API latency excludes simulation; wall time includes waiting and simulation. Each lane pauses its own game time during both; episode lanes run independently in parallel.",
        "- The request and score semantics are recorded in each ranking event. Choice scores are not calibrated across providers; legacy predicate scores are independent and unnormalized.",
        "- Search and offline fixtures make no API calls. Reported usage is recorded per successful request; monetary cost is unknown.",
        "- Follow-ups are hypothetical and never automatically executed. With the optional survival guard, a predicted fatal choice can be replaced using the same simulated evidence.",
        "- Small samples are diagnostic, not evidence of statistical superiority. Model responses need not be deterministic.",
        "- Each JSONL contains the initial fingerprint, canonical evidence, sanitized request body, chosen move, actual controls, and final state.",
        "- Unavailable model identifiers or usage are unknown. Errors are not scored as gameplay deaths.",
    ]
    if track == "realtime":
        lines = [
            line.replace(
                "Game time pauses during both.", "Game time continues during both."
            ).replace(
                "Each lane pauses its own game time during both; episode lanes run independently in parallel.",
                "Game time continues during simulation and inference. Latency affects survival.",
            )
            for line in lines
        ]
        lines += [
            "",
            "## Real-time decision age",
            "",
            "This is a separate latency-sensitive track. Bootstrap is neutral; then the last move continues while the next decision is pending. Predictions describe an older snapshot and need not match live execution.",
            "",
            "| Policy | Median age (frames) | Maximum age (frames) |",
            "|---|---:|---:|",
        ]
        for item in aggregate:
            lines.append(
                f"| {item['policy']} | {item['decision_age_p50_frames']} | {item['decision_age_max_frames']} |"
            )
    (path / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
