import json
import time
from pathlib import Path

import pytest

from mario_eval.simulation import (
    CANDIDATES,
    BudgetStop,
    MarioSimulator,
    SimulationConfig,
    WorkBudget,
    canonical_state,
    selection_diagnostics,
    survival_selection,
)

CASES = json.loads((Path(__file__).parent / "fixtures/zoom_survival_regressions.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_guard_avoids_recorded_zoom_failures(case):
    sim = MarioSimulator()
    config = SimulationConfig()
    try:
        for action, count in case["prefix"]:
            for _ in range(count):
                sim.step(action)
        assert sim.digest() == case["digest"]
        outcomes = sim.explore(config, WorkBudget(20000, time.monotonic() + 120))
        assert sim.digest() == case["digest"]
        canonical = canonical_state(sim, outcomes, config)
        selection = survival_selection(canonical, case["candidate"], case["scores"])
        assert selection["overridden"]
        assert selection["applied_candidate"] == case["expected_candidate"]
        assert selection["reason"] == case["expected_reason"]
        selected = outcomes[case["candidate"]]
        if selected["status"] == "unknown":
            assert {c["id"] for c in selected["continuations"]} == set(CANDIDATES)
            assert all(c["status"] == "dead" for c in selected["continuations"])
            diagnostics = selection_diagnostics(canonical, case["candidate"])
            assert diagnostics["unknown_outcome"]
            assert not diagnostics["incomplete_followup_coverage"]
            # Old corpora keep their evidence; interruption during new airborne
            # expansion must still restore the exact live checkpoint.
            legacy = sim.explore(
                SimulationConfig(continuation_set="all-seven-v1"),
                WorkBudget(20000, time.monotonic() + 120),
                order=(case["candidate"],),
            )
            assert not legacy[case["candidate"]]["continuations"]
            with pytest.raises(BudgetStop, match="simulation_cap"):
                sim.explore(
                    config,
                    WorkBudget(selected["frames"] + 2, time.monotonic() + 120),
                    order=(case["candidate"],),
                )
            assert sim.digest() == case["digest"]
        result = sim.execute(selection["applied_candidate"], config)
        assert result["status"] == "alive"
        assert result["digest_after"] == outcomes[selection["applied_candidate"]]["digest_after"]
        # An actually surviving continuation, not just avoiding death on this move.
        viable = next(
            c
            for c in outcomes[selection["applied_candidate"]]["continuations"]
            if c["status"] in ("alive", "clear")
        )
        assert sim.execute(viable["id"], config)["status"] in ("alive", "clear")
    finally:
        sim.close()


def outcome(status, continuations=()):
    return {"status": status, "dx": 0, "continuations": list(continuations)}


def test_guard_does_not_infer_death_from_unknown_or_partial_evidence():
    fatal = [{"id": c, "status": "dead", "frames": 1} for c in CANDIDATES]
    for selected in (
        outcome("unknown"),
        outcome("alive", fatal[:3]),
        outcome("unknown", [{"id": "wait", "status": "alive", "frames": 52}]),
    ):
        c = {"outcomes": {"run": selected, "wait": outcome("alive")}}
        assert not survival_selection(c, "run", {"run": 0.9, "wait": 0.1})["overridden"]


def test_guard_no_survivor_and_clear_precedence():
    c = {"outcomes": {"run": outcome("dead"), "jump": outcome("dead")}}
    result = survival_selection(c, "run", {"run": 0.9, "jump": 0.1})
    assert not result["overridden"]
    assert result["reason"] == "no_surviving_alternative"
    c["outcomes"].update(wait=outcome("alive"), back=outcome("clear"))
    assert (
        survival_selection(c, "run", {"run": 0.9, "jump": 0.1, "wait": 0.8, "back": 0.01})[
            "applied_candidate"
        ]
        == "back"
    )


def test_unknown_terminal_is_not_expanded():
    sim = MarioSimulator()
    try:
        wrapper = next(w for w in sim.chain if hasattr(w, "_elapsed_steps"))
        wrapper._max_episode_steps = 2
        initial = sim.digest()
        outcomes = sim.explore(SimulationConfig(), WorkBudget(100, time.monotonic() + 30))
        assert all(o["status"] == "unknown" and not o["continuations"] for o in outcomes.values())
        assert sim.digest() == initial
    finally:
        sim.close()
