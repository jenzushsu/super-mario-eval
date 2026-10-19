import copy
import json
import time
from pathlib import Path

import pytest

from mario_eval.assisted import reconstruct_prefix
from mario_eval.rankers import payload_for
from mario_eval.simulation import (
    MarioSimulator,
    SimulationConfig,
    WorkBudget,
    canonical_state,
    progress_summary,
    selection_diagnostics,
)


def budget():
    return WorkBudget(20000, time.monotonic() + 120)


def test_uploaded_zoom_stall_exposes_forward_route_and_repeated_choices():
    case = json.loads((Path(__file__).parent / "fixtures/zoom_stall_cycle.json").read_text())
    sim = MarioSimulator(seed=case["seed"])
    config = SimulationConfig()
    prefix = []
    try:
        for index, event in enumerate(case["executions"], 1):
            if index == 26:
                evidence = canonical_state(sim, sim.explore(config, budget()), config)
                hop = evidence["outcomes"]["hop"]["progress_summary"]
                jump = evidence["outcomes"]["jump"]["progress_summary"]
                assert hop["best_surviving_two_move_dx"] == 79
                assert hop["best_surviving_followups"] == ["jump"]
                assert hop["gain_beyond_best_x"] == 79
                assert jump["best_surviving_two_move_dx"] == 48
                assert jump["surviving_forward_followups"] == []
                jev = payload_for("jev", evidence)
                zoom = payload_for("zoom", evidence)
                assert jev["state"] == json.loads(zoom["input"])
                assert {
                    c["value"]: c["description"] for c in zoom["questions"][0]["choices"]
                } == jev["questions"]["action"]["criteria"]
            before = sim.state()
            actual = sim.execute(event["candidate"], config)
            controls = [a for a, n in event["controls"] for _ in range(n)]
            assert actual["actions"] == controls
            assert sim.digest() == event["after_digest"]
            sim.record_decision(event["candidate"], before, True)
            prefix.extend(controls)
        checkpoint = sim.checkpoint()
        history = copy.deepcopy(sim.recent_decisions)
        outcomes = sim.explore(config, budget())
        assert sim.recent_decisions == history
        evidence = canonical_state(sim, outcomes, config)
        assert len(history) == 12
        assert (
            evidence["outcomes"]["walk"]["progress_summary"]["prior_attempts_without_new_best"] == 3
        )
        assert selection_diagnostics(evidence, "walk")["repeated_area_choice"]
        assert evidence["history"]["current_area_previous_visits"] >= 3
        sim.execute("back", config)
        sim.record_decision("back", evidence["state"], True)
        sim.restore(checkpoint)
        assert sim.recent_decisions == history
        # Corpus reconstruction verifies names, boundaries and results against controls.
        corpus_case = {"prefix": prefix, "decision_history": history}
        other = MarioSimulator(seed=case["seed"])
        try:
            reconstruct_prefix(other, corpus_case, config, budget())
            assert other.digest() == sim.digest()
            assert other.recent_decisions == history
        finally:
            other.close()
        bad = copy.deepcopy(corpus_case)
        bad["decision_history"][-1]["after"]["best_x"] += 1
        other = MarioSimulator(seed=case["seed"])
        try:
            with pytest.raises(ValueError, match="does not reproduce"):
                reconstruct_prefix(other, bad, config, budget())
        finally:
            other.close()
    finally:
        sim.close()


def test_unknown_untested_and_retreat_progress_are_not_zero_or_guaranteed_safe():
    state = {"x": 100, "best_x": 120, "y": 79, "grounded": True, "status": "small"}
    outcome = {"status": "unknown", "x_after": 90, "dx": -10, "continuations": []}
    empty = progress_summary(outcome, state, [], "back")
    assert empty["best_surviving_two_move_dx"] is None
    assert empty["gain_beyond_best_x"] is None
    outcome["continuations"] = [
        {"id": "run", "status": "unknown", "dx": 1000},
        {"id": "jump", "status": "dead", "dx": 1000},
        {"id": "hop", "status": "alive", "dx": 50},
    ]
    actual = progress_summary(outcome, state, [], "back")
    assert actual["best_surviving_two_move_dx"] == 40
    assert actual["gain_beyond_best_x"] == 20
    assert actual["best_surviving_followups"] == ["hop"]
