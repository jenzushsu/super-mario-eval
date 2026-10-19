"""Original bounded lookahead implementation; no code copied from 4esv/jev-mario."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
from typesafe_mario.actions import ACTION_TO_INDEX, Action
from typesafe_mario.runner import create_mario_env

ACTION_SET = "simple-macros-v1"
CANDIDATES = ("run", "walk", "jump", "run_jump", "hop", "wait", "back")
FOLLOW_UPS = CANDIDATES


@dataclass(frozen=True)
class SimulationConfig:
    horizon: int = 48
    landing_cap: int = 72
    settle: int = 4
    continuation_depth: int = 1
    continuation_set: str = "all-seven-airborne-v2"

    def __post_init__(self):
        if self.continuation_set not in ("all-seven-v1", "all-seven-airborne-v2"):
            raise ValueError("Unsupported continuation set")
        if self.horizon < 40 or self.landing_cap < 0 or self.settle < 0:
            raise ValueError("horizon must be >=40; landing cap and settle must be nonnegative")
        if self.continuation_depth not in (0, 1):
            raise ValueError("Supported continuation depths: 0 or 1")


class BudgetStop(RuntimeError):
    pass


@dataclass
class WorkBudget:
    limit: int
    deadline: float
    used: int = 0
    cancelled: Callable[[], bool] = lambda: False

    def step(self):
        if self.cancelled():
            raise BudgetStop("cancelled")
        if time.monotonic() >= self.deadline:
            raise BudgetStop("wall_time_cap")
        if self.used >= self.limit:
            raise BudgetStop("simulation_cap")
        self.used += 1


def _plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


class MarioSimulator:
    def __init__(self, env_id="SuperMarioBros-1-1-v0", seed=123):
        self.env_id, self.seed = env_id, seed
        self.env = create_mario_env(env_id, render_mode="rgb_array")
        frame, info = self.env.reset(seed=seed)
        self.frame, self.info = frame.copy(), _plain(info)
        self.terminated = self.truncated = False
        self.frames = 0
        self.reward = 0.0
        self.best_x = self.x
        self.last_gain_frame = 0
        self.recent_controls = []
        self.chain = []
        wrapper = self.env
        while True:
            self.chain.append(wrapper)
            if not hasattr(wrapper, "env"):
                break
            wrapper = wrapper.env
        self.core = self.chain[-1]
        if not hasattr(self.core, "dump_state"):
            self.close()
            raise RuntimeError("This emulator does not support native snapshots")

    @property
    def x(self):
        return int(self.info.get("x_pos", 0))

    @property
    def grounded(self):
        return int(self.core.ram[0x001D]) == 0

    @property
    def done(self):
        return self.terminated or self.truncated or self.dead or self.clear

    @property
    def dead(self):
        return bool(self.info.get("death", self.info.get("is_dead", False)))

    @property
    def clear(self):
        return bool(self.info.get("clear", self.info.get("flag_get", False)))

    def close(self):
        self.env.close()

    def python_state(self):
        # Capture Python-side reward shaping and Gym wrapper counters as well as RNGs.
        states = []
        for wrapper in self.chain:
            values = {}
            for key, value in vars(wrapper).items():
                if isinstance(value, (str, bool, int, float, dict, list, tuple, type(None))):
                    values[key] = copy.deepcopy(value)
                elif isinstance(value, np.random.Generator):
                    values[key] = ("numpy_generator", copy.deepcopy(value.bit_generator.state))
            states.append(values)
        return states

    def checkpoint(self):
        return (
            self.core.dump_state(),
            self.python_state(),
            self.frame.copy(),
            copy.deepcopy(self.info),
            self.terminated,
            self.truncated,
            self.frames,
            self.reward,
            self.best_x,
            self.last_gain_frame,
            copy.deepcopy(self.recent_controls),
        )

    def restore(self, checkpoint):
        native, states, frame, info, term, trunc, frames, reward, best, last_gain, history = (
            checkpoint
        )
        self.core.load_state(native)
        for wrapper, state in zip(self.chain, states, strict=True):
            for key, value in state.items():
                if key == "controllers":
                    for current, saved in zip(wrapper.controllers, value, strict=True):
                        current[...] = saved
                elif isinstance(value, tuple) and value and value[0] == "numpy_generator":
                    getattr(wrapper, key).bit_generator.state = copy.deepcopy(value[1])
                else:
                    setattr(wrapper, key, copy.deepcopy(value))
        self.frame, self.info = frame.copy(), copy.deepcopy(info)
        self.terminated, self.truncated = term, trunc
        self.frames, self.reward, self.best_x = frames, reward, best
        self.last_gain_frame = last_gain
        self.recent_controls = copy.deepcopy(history)

    def digest(self):
        metadata = json.dumps(
            _plain(
                {
                    "wrappers": [
                        {k: v for k, v in state.items() if k != "_rom_path"}
                        for state in self.python_state()
                    ],
                    "info": self.info,
                    "terminated": self.terminated,
                    "truncated": self.truncated,
                    "frames": self.frames,
                    "reward": self.reward,
                    "best_x": self.best_x,
                }
            ),
            sort_keys=True,
            allow_nan=False,
        ).encode()
        return hashlib.sha256(bytes(self.core.ram) + self.frame.tobytes() + metadata).hexdigest()

    def state(self):
        return {
            "x": self.x,
            "y": int(self.info.get("y_pos", 0)),
            "grounded": self.grounded,
            "best_x": self.best_x,
            "game_frames": self.frames,
            "status": self.info.get("status"),
            "time": self.info.get("time"),
            "dead": self.dead,
            "clear": self.clear,
        }

    def step(self, action):
        if self.done:
            raise ValueError("Cannot step a terminated episode")
        before_x = self.x
        frame, reward, term, trunc, info = self.env.step(ACTION_TO_INDEX[Action(action)])
        self.frame, self.info = frame.copy(), _plain(info)
        self.last_action = str(action)
        self.terminated, self.truncated = bool(term), bool(trunc)
        self.frames += 1
        self.reward += float(reward)
        if self.x > self.best_x:
            self.last_gain_frame = self.frames
        self.best_x = max(self.best_x, self.x)
        if self.recent_controls and self.recent_controls[-1]["action"] == str(action):
            recent = self.recent_controls[-1]
            recent["frames"] += 1
            recent["dx"] += self.x - before_x
        else:
            self.recent_controls.append(
                {"action": str(action), "frames": 1, "dx": self.x - before_x}
            )
            self.recent_controls = self.recent_controls[-8:]

    def execute(self, candidate, config, before_step=lambda: None, on_frame=lambda: None):
        if candidate not in CANDIDATES:
            raise ValueError("Unknown candidate")
        start_x, start_frames = self.x, self.frames
        actions = []
        jump = candidate in ("jump", "run_jump", "hop")
        button = {
            "run": "right_run",
            "walk": "right",
            "jump": "right_jump",
            "run_jump": "right_run_jump",
            "hop": "right_jump",
            "wait": "noop",
            "back": "left",
        }[candidate]
        release = "right_run" if candidate == "run_jump" else "right" if jump else button
        hold = 8 if candidate == "hop" else 32

        def advance(action):
            before_step()
            self.step(action)
            actions.append(action)
            on_frame()

        for index in range(config.horizon):
            if self.done:
                break
            # A neutral release edge precedes a fresh grounded jump; no directed edge step.
            if jump and index == 0 and self.grounded:
                action = "noop"
            elif jump and index >= hold:
                action = release
            else:
                action = button
            advance(action)
        for _ in range(config.landing_cap):
            if self.done or self.grounded:
                break
            advance(release)
        for _ in range(config.settle):
            if self.done:
                break
            advance("noop")
        unknown = self.truncated or (not self.done and not self.grounded)
        status = (
            "clear"
            if self.clear
            else "dead"
            if self.dead
            else "unknown"
            if unknown or self.terminated
            else "alive"
        )
        return {
            "id": candidate,
            "status": status,
            "dx": self.x - start_x,
            "frames": self.frames - start_frames,
            "grounded": self.grounded,
            "x_after": self.x,
            "state_after": self.state(),
            "digest_after": self.digest(),
            "actions": actions,
        }

    def explore(self, config, budget, order=CANDIDATES):
        root = self.checkpoint()
        root_digest = self.digest()
        outcomes = {}
        try:
            for candidate in order:
                self.restore(root)
                outcome = self.execute(candidate, config, before_step=budget.step)
                outcome["continuations"] = []
                expandable = outcome["status"] == "alive" or (
                    outcome["status"] == "unknown"
                    and not self.done
                    and config.continuation_set == "all-seven-airborne-v2"
                )
                if expandable and config.continuation_depth:
                    endpoint = self.checkpoint()
                    for follow in FOLLOW_UPS:
                        self.restore(endpoint)
                        continuation = self.execute(follow, config, before_step=budget.step)
                        outcome["continuations"].append(
                            {k: continuation[k] for k in ("id", "status", "dx", "frames")}
                        )
                outcomes[candidate] = outcome
        finally:
            self.restore(root)
        if self.digest() != root_digest:
            raise RuntimeError("Snapshot exploration changed the starting state")
        return {candidate: outcomes[candidate] for candidate in CANDIDATES if candidate in outcomes}


def canonical_state(sim, outcomes, config):
    from typesafe_mario.state import MarioStateParser

    observation = MarioStateParser().parse(sim.info, sim.core.ram).to_state()
    terrain = observation["terrain"]
    hazard = observation["hazard"]
    tags = []
    if hazard.get("upcoming_enemies"):
        tags.append("enemy")
    if terrain.get("gap_ahead") or terrain.get("gap_distance_tiles") is not None:
        tags.append("gap")
    if terrain.get("obstacle_ahead") or terrain.get("obstacle_distance_tiles") is not None:
        tags.append("obstacle")
    if not tags:
        tags.append("open")
    return {
        "scene_tags": tags,
        "objective": "Reach the flag while avoiding death; use only the measured finite-horizon outcomes.",
        "mode": "assisted-outcome-ranking",
        "action_set": ACTION_SET,
        "simulation": asdict(config),
        "state": sim.state(),
        "history": {
            "recent_controls": copy.deepcopy(sim.recent_controls),
            "frames_since_best_x": sim.frames - sim.last_gain_frame,
            "note": "Actual executed controls only; consecutive identical controls are grouped. No new best x includes deliberate retreat.",
        },
        "outcomes": {
            name: {
                "continuation_summary": continuation_summary(value),
                **{
                    k: value[k]
                    for k in (
                        "status",
                        "dx",
                        "frames",
                        "grounded",
                        "x_after",
                        "continuations",
                    )
                },
            }
            for name, value in outcomes.items()
        },
    }


def rank_outcome(outcome):
    viable = [x for x in outcome["continuations"] if x["status"] in ("alive", "clear")]
    return (
        outcome["status"] == "clear",
        outcome["status"] == "alive",
        bool(viable) if outcome["continuations"] else outcome["status"] == "alive",
        outcome["dx"] + max((x["dx"] for x in viable), default=0),
        outcome["dx"],
        len(viable),
    )


def continuation_summary(outcome):
    followups = outcome["continuations"]
    tested = {v["id"] for v in followups}
    surviving = [v["id"] for v in followups if v["status"] in ("alive", "clear")]
    fatal = [v for v in followups if v["status"] == "dead"]
    return {
        "tested": len(tested),
        "available": len(CANDIDATES),
        "coverage": "complete"
        if tested == set(CANDIDATES)
        else "partial"
        if tested
        else "not_tested",
        "surviving": surviving,
        "fatal": len(fatal),
        "unknown": sum(v["status"] == "unknown" for v in followups),
        "all_tested_fatal": bool(followups) and len(fatal) == len(followups),
        "earliest_fatal_frames": min((v["frames"] for v in fatal), default=None),
    }


def selection_diagnostics(canonical, candidate):
    outcome = canonical["outcomes"][candidate]
    followups = continuation_summary(outcome)
    return {
        "immediate_death": outcome["status"] == "dead",
        "fatal_when_survivor_available": outcome["status"] == "dead"
        and any(v["status"] in ("alive", "clear") for v in canonical["outcomes"].values()),
        "all_tested_followups_fatal": followups["all_tested_fatal"],
        "unknown_outcome": outcome["status"] == "unknown",
        "incomplete_followup_coverage": outcome["status"] in ("alive", "unknown")
        and followups["coverage"] != "complete",
        "zero_progress": outcome["dx"] <= 0 and outcome["status"] != "clear",
        "repeated_no_progress": outcome["dx"] <= 0
        and outcome["status"] != "clear"
        and canonical.get("history", {}).get("frames_since_best_x", 0)
        >= canonical["simulation"]["horizon"],
    }


def survival_selection(canonical, proposed, scores):
    """Bounded survival assistance; never infer fatality from missing follow-ups.

    Return the model choice unchanged unless it predicts death or a completely
    tested fatal continuation set, and an evaluated alternative survives.
    Model probabilities rank the eligible alternatives; this is not a search policy.
    """
    outcomes = canonical["outcomes"]
    selected = outcomes[proposed]
    followups = continuation_summary(selected)
    reason = None
    if selected["status"] == "dead":
        reason = "predicted_death"
    elif selected["status"] != "clear" and (
        followups["coverage"] == "complete" and followups["all_tested_fatal"]
    ):
        reason = "all_seven_followups_fatal"

    def viable(outcome):
        if outcome["status"] == "clear":
            return True
        if outcome["status"] not in ("alive", "unknown"):
            return False
        summary = continuation_summary(outcome)
        return bool(summary["surviving"]) or (
            outcome["status"] == "alive" and summary["coverage"] == "not_tested"
        )

    eligible = [key for key, outcome in outcomes.items() if viable(outcome)]
    applied = proposed
    if reason and eligible:
        applied = max(eligible, key=lambda key: (outcomes[key]["status"] == "clear", scores[key]))
    return {
        "proposed_candidate": proposed,
        "applied_candidate": applied,
        "overridden": applied != proposed,
        "reason": reason if applied != proposed else "no_surviving_alternative" if reason else None,
        "eligible_candidates": eligible,
    }
