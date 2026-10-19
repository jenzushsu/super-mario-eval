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
