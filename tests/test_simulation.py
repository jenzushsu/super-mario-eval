import time

import pytest

from mario_eval.simulation import (
    CANDIDATES,
    BudgetStop,
    MarioSimulator,
    SimulationConfig,
    WorkBudget,
)


@pytest.fixture(scope="module")
def simulator():
    sim = MarioSimulator()
    yield sim
    sim.close()


@pytest.fixture
def sim(simulator):
    checkpoint = simulator.checkpoint()
    yield simulator
    simulator.restore(checkpoint)


def budget(limit=20000):
    return WorkBudget(limit, time.monotonic() + 120)


def test_exploration_is_order_independent_and_execution_matches(sim):
    config = SimulationConfig(continuation_depth=0)
    initial = sim.digest()
    first = sim.explore(config, budget())
    assert sim.digest() == initial
    reverse = sim.explore(config, budget(), order=tuple(reversed(CANDIDATES)))
    assert first == reverse
    assert sim.digest() == initial
    result = sim.execute("run_jump", config)
    assert result["actions"][0] == "noop"
    assert result["actions"] == first["run_jump"]["actions"]
    assert result["digest_after"] == first["run_jump"]["digest_after"]
    assert sim.frames == len(result["actions"])


def test_budget_exhaustion_restores_everything(sim):
    initial = sim.digest()
    with pytest.raises(BudgetStop, match="simulation_cap"):
        sim.explore(SimulationConfig(), budget(3))
    assert sim.digest() == initial


def test_terminal_snapshot_restores_reward_and_wrapper_counters(sim):
    time_limit = next(wrapper for wrapper in sim.chain if hasattr(wrapper, "_elapsed_steps"))
    time_limit._max_episode_steps = 2
    start = sim.checkpoint()
    initial = sim.digest()
    first = sim.execute("run", SimulationConfig(continuation_depth=0))
    assert sim.truncated
    assert first["status"] == "unknown"
    assert len(first["actions"]) == 2
    sim.restore(start)
    assert sim.digest() == initial
    assert not sim.done
    again = sim.execute("run", SimulationConfig(continuation_depth=0))
    assert again == first


def test_negative_or_unsupported_settings_rejected():
    with pytest.raises(ValueError):
        SimulationConfig(horizon=1)
    with pytest.raises(ValueError):
        SimulationConfig(continuation_depth=2)


def test_history_is_restored_and_reconstructed_from_controls(sim):
    from mario_eval.simulation import canonical_state

    config = SimulationConfig(continuation_depth=0)
    before = sim.checkpoint()
    executed = sim.execute("run", config)
    sim.execute("wait", config)
    history = canonical_state(sim, {}, config)["history"]
    assert history["recent_controls"]
    checkpoint = sim.checkpoint()
    sim.explore(config, budget())
    assert canonical_state(sim, {}, config)["history"] == history
    sim.restore(before)
    for action in executed["actions"]:
        sim.step(action)
    simulated = canonical_state(sim, {}, config)["history"]
    sim.restore(before)
    sim.execute("run", config)
    assert canonical_state(sim, {}, config)["history"] == simulated
    sim.restore(checkpoint)


def regression_cases():
    import json
    from pathlib import Path

    return json.loads((Path(__file__).parent / "fixtures/mario_regressions.json").read_text())


@pytest.mark.parametrize("case", regression_cases(), ids=lambda case: case["name"])
def test_uploaded_failure_and_escape_states(sim, case):
    from mario_eval.simulation import canonical_state

    for action, count in case["prefix"]:
        for _ in range(count):
            sim.step(action)
    assert sim.digest() == case["digest"]
    history = canonical_state(sim, {}, SimulationConfig())["history"]
    outcomes = sim.explore(SimulationConfig(), budget())
    assert sim.digest() == case["digest"]
    assert canonical_state(sim, {}, SimulationConfig())["history"] == history
    for outcome in outcomes.values():
        if outcome["status"] == "alive":
            assert {v["id"] for v in outcome["continuations"]} == set(CANDIDATES)
    from mario_eval.simulation import selection_diagnostics

    evidence = canonical_state(sim, outcomes, SimulationConfig())
    diagnostics = selection_diagnostics(evidence, case["candidate"])
    assert diagnostics["all_tested_followups_fatal"] == (case["surviving_followup"] is None)
    assert not diagnostics["incomplete_followup_coverage"]
    selected = outcomes[case["candidate"]]
    if case["surviving_followup"]:
        follow = next(v for v in selected["continuations"] if v["id"] == case["surviving_followup"])
        assert follow["status"] == "alive"
    else:
        assert all(v["status"] == "dead" for v in selected["continuations"])
        assert any(
            v["status"] == "alive" and any(c["status"] == "alive" for c in v["continuations"])
            for v in outcomes.values()
        )
