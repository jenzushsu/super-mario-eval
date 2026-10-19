import json
import time

from test_assisted import options

from mario_eval import assisted, realtime
from mario_eval.rankers import ProviderError


def test_live_game_advances_and_cancels_pending_inference(tmp_path, monkeypatch):
    real = realtime.Ranker
    entered = []

    class Blocked(real):
        def choose(self, canonical, timeout=None, cancelled=lambda: False):
            entered.append(self.provider)
            while not cancelled():
                time.sleep(0.005)
            raise ProviderError("cancelled", "Request cancelled")

    monkeypatch.setattr(realtime, "Ranker", Blocked)
    # Isolate blocked inference from machine-dependent lookahead duration.
    monkeypatch.setattr(
        realtime.MarioSimulator,
        "explore",
        lambda sim, config, budget: {
            "run": {
                "status": "alive",
                "dx": 0,
                "frames": 48,
                "grounded": True,
                "x_after": sim.x,
                "continuations": [],
            }
        },
    )
    args = options(tmp_path, zoom_question="choice", game_frames=60)
    assert realtime.run(args) == 0
    assert len(entered) == 3
    root = next(tmp_path.iterdir())
    rows = json.loads((root / "summary.json").read_text())["runs"]
    assert all(row["reason"] == "game_frame_cap" and row["game_frames"] == 60 for row in rows)
    assert all(row["decisions"] == 0 for row in rows)
    for policy in ("fixture-jev", "fixture-zoom", "search"):
        path = root / f"{policy}-001.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert any(r["event"] == "discarded_decision" for r in records)
        assert assisted.replay(path) == 0


def test_arriving_decision_has_age_and_replayable_held_controls(tmp_path, monkeypatch):
    real = realtime.Ranker

    class Delayed(real):
        def choose(self, canonical, timeout=None, cancelled=lambda: False):
            time.sleep(0.15)
            return super().choose(canonical, timeout, cancelled)

    monkeypatch.setattr(realtime, "Ranker", Delayed)
    args = options(tmp_path, zoom_question="choice", game_frames=180)
    assert realtime.run(args) == 0
    root = next(tmp_path.iterdir())
    result = json.loads((root / "summary.json").read_text())
    assert result["track"] == "realtime"
    for row in result["runs"]:
        assert row["reason"] == "decision_cap"
        assert row["decisions"] == 1
        assert row["decision_age_frames"][0] > 0
        records = [
            json.loads(line)
            for line in (root / f"{row['policy']}-001.jsonl").read_text().splitlines()
        ]
        evidence = next(r for r in records if r["event"] == "evidence")
        ranked = next(r for r in records if r["event"] == "ranking")
        assert evidence["canonical"]["state"]["game_frames"] == ranked["observed_frame"]
        assert ranked["applied_frame"] - ranked["observed_frame"] == ranked["decision_age_frames"]
        assert assisted.replay(root / f"{row['policy']}-001.jsonl") == 0
    report = (root / "report.md").read_text()
    assert "Game time continues" in report
    assert "pauses its own game time" not in report


def test_held_jump_releases_button_without_repeating_jump_edges():
    move = realtime.HeldMove("run_jump")
    assert move.next(True) == "noop"
    assert all(move.next(False) == "right_run_jump" for _ in range(31))
    assert move.next(False) == "right_run"
    assert move.next(True) == "right_run"
    assert realtime.HeldMove().next(True) == "noop"


def test_realtime_provider_failure_stops_lane_without_fallback(tmp_path, monkeypatch):
    real = realtime.Ranker

    class Failing(real):
        def choose(self, canonical, timeout=None, cancelled=lambda: False):
            if self.provider == "fixture-zoom":
                raise ProviderError("authentication", "HTTP 403")
            return super().choose(canonical, timeout, cancelled)

    monkeypatch.setattr(realtime, "Ranker", Failing)
    assert realtime.run(options(tmp_path, zoom_question="choice", game_frames=180)) == 1
    root = next(tmp_path.iterdir())
    rows = json.loads((root / "summary.json").read_text())["runs"]
    zoom = next(row for row in rows if row["policy"] == "fixture-zoom")
    assert zoom["reason"] == "provider_error"
    assert zoom["decisions"] == 0
    assert zoom["error"]["category"] == "authentication"
    assert all(row["decisions"] == 1 for row in rows if row is not zoom)
    assert assisted.replay(root / "fixture-zoom-001.jsonl") == 0
