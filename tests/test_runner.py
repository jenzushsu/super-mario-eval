import json
from types import SimpleNamespace

from mario_eval import cli
from mario_eval.zoom import ZoomAPIError


def test_provider_failure_is_logged_while_other_lane_continues(tmp_path, monkeypatch):
    class Env:
        def reset(self, **kwargs):
            return None, {"x_pos": 40}

        def step(self, action):
            return None, 1, False, False, {"x_pos": 45}

        def close(self):
            pass

    class Snapshot:
        stalled_steps = 0
        grounded = True

        def to_state(self):
            return {"player": {"x": 40}}

    class Parser:
        def __init__(self, **kwargs):
            pass

        def parse(self, *args, **kwargs):
            return Snapshot()

    class BrokenPolicy:
        def choose(self, *args):
            raise ZoomAPIError("Zoom Decisions returned HTTP 401")

    policies = iter([BrokenPolicy(), cli.HeuristicPolicy()])
    monkeypatch.setattr(cli, "HeuristicPolicy", lambda: next(policies))
    monkeypatch.setattr(cli, "create_mario_env", lambda *args, **kwargs: Env())
    monkeypatch.setattr(cli, "MarioStateParser", Parser)
    args = SimpleNamespace(
        offline=True,
        artifacts_dir=tmp_path,
        env="test",
        seed=123,
        frames_per_decision=8,
        max_decisions=2,
        headless=True,
        screenshot=None,
        exit_when_done=True,
    )
    assert cli.run(args) == 1
    run_dir = next(tmp_path.iterdir())
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary[0]["error"]["detail"] == "Zoom Decisions returned HTTP 401"
    assert summary[0]["error"]["decision_index"] == 1
    assert summary[1]["count"] == 2
    failure = json.loads((run_dir / "jev.jsonl").read_text())
    assert failure["event"] == "provider_error"
    records = [json.loads(line) for line in (run_dir / "zoom.jsonl").read_text().splitlines()]
    assert len(records) == 2
    assert records[-1]["emulator_frames"] == 16
    assert len(records[-1]["executed_actions"]) == 8
    assert "state_after" in records[-1]
    assert summary[1]["simulated_seconds"] == 16 / 60


def test_grounded_jump_releases_once_and_preserves_airborne_hold():
    from typesafe_mario.actions import Action

    grounded = SimpleNamespace(grounded=True)
    airborne = SimpleNamespace(grounded=False)
    assert cli.controller_action(Action.RIGHT_RUN_JUMP, grounded, 0) == Action.RIGHT_RUN
    assert cli.controller_action(Action.RIGHT_RUN_JUMP, grounded, 1) == Action.RIGHT_RUN_JUMP
    assert cli.controller_action(Action.RIGHT_RUN_JUMP, airborne, 0) == Action.RIGHT_RUN_JUMP
    assert cli.controller_action(Action.RIGHT, grounded, 0) == Action.RIGHT
