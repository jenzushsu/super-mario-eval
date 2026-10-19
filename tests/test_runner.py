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
    assert len((run_dir / "zoom.jsonl").read_text().splitlines()) == 2
