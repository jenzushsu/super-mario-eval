import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mario_eval import assisted
from mario_eval.rankers import ProviderError
from mario_eval.simulation import BudgetStop


def options(tmp_path, **changes):
    values = {
        "horizon": 48,
        "landing_cap": 72,
        "settle": 4,
        "depth": 0,
        "offline": True,
        "headless": True,
        "exit_when_done": True,
        "screenshot": None,
        "timeout": 1,
        "model": "jev-latest",
        "artifacts_dir": tmp_path,
        "env": "SuperMarioBros-1-1-v0",
        "seed": 123,
        "episodes": 1,
        "max_decisions": 1,
        "game_frames": 3600,
        "simulation_frames": 20000,
        "wall_seconds": 90,
        "stall_frames": 360,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def forbid_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Unexpected network request in an offline workflow")

    monkeypatch.setattr("urllib.request.urlopen", fail)


def test_offline_episode_partial_execution_and_replay(tmp_path, monkeypatch):
    forbid_network(monkeypatch)
    assert assisted.episode_run(options(tmp_path, game_frames=3)) == 0
    root = next(tmp_path.iterdir())
    summary = json.loads((root / "summary.json").read_text())
    assert len(summary["runs"]) == 3
    assert {row["reason"] for row in summary["runs"]} == {"game_frame_cap"}
    assert {row["api_attempts"] for row in summary["runs"]} == {0}
    assert {row["game_frames"] for row in summary["runs"]} == {3}
    log = root / "fixture-jev-001.jsonl"
    assert assisted.replay(log) == 0
    records = [json.loads(line) for line in log.read_text().splitlines()]
    execution = next(r for r in records if r["event"] == "execution")
    assert execution["complete"] is False
    execution["actions"][1] = "left"
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text("\n".join(json.dumps(r) for r in records))
    with pytest.raises(ValueError, match="diverged"):
        assisted.replay(tampered)


def test_corpus_evaluation_and_tamper_detection(tmp_path, monkeypatch):
    forbid_network(monkeypatch)
    args = options(tmp_path / "capture")
    assert assisted.episode_run(args, capture=True) == 0
    root = next(args.artifacts_dir.iterdir())
    corpus_path = root / "corpus.json"
    corpus = json.loads(corpus_path.read_text())
    assert corpus["cases"]
    assert "missing_coverage" in corpus
    evaluation = options(tmp_path / "evaluation", corpus=corpus_path)
    assert assisted.evaluate_corpus(evaluation) == 0
    output = next(evaluation.artifacts_dir.iterdir())
    events = [json.loads(line) for line in (output / "rankings.jsonl").read_text().splitlines()]
    events = [event for event in events if event["event"] == "ranking"]
    assert len(events) == 3
    assert events[0]["canonical"] == events[1]["canonical"] == events[2]["canonical"]
    assert all("candidate" in event for event in events)
    config = json.loads((output / "config.json").read_text())
    assert (
        config["corpus_sha256"] == hashlib.sha256((output / "corpus.json").read_bytes()).hexdigest()
    )
    assert config["limits"]["max_decisions"] == 1
    summary = json.loads((output / "summary.json").read_text())
    assert summary["shared_validation"]["simulation_frames"] > 0
    assert summary["shared_validation"]["wall_seconds"] > 0
    assert "Shared corpus validation:" in (output / "report.md").read_text()
    capped = options(tmp_path / "capped", corpus=corpus_path, simulation_frames=1)
    with pytest.raises(BudgetStop, match="simulation_cap"):
        assisted.evaluate_corpus(capped)
    capped_root = next(capped.artifacts_dir.iterdir())
    stopped = json.loads((capped_root / "summary.json").read_text())
    assert stopped["runs"][0]["reason"] == "simulation_cap"
    assert stopped["runs"][0]["error"]["category"] == "simulation_cap"
    assert stopped["shared_validation"]["simulation_frames"] == 1
    real_ranker = assisted.Ranker

    class RejectedRanker:
        def __init__(self, provider, *args):
            self.provider = provider

        def choose(self, canonical, timeout=None):
            if self.provider in ("jev", "zoom"):
                raise ProviderError("authentication", "HTTP 403")
            return real_ranker("search").choose(canonical)

    monkeypatch.setattr(assisted, "Ranker", RejectedRanker)
    failed = options(tmp_path / "failed", corpus=corpus_path, offline=False)
    assert assisted.evaluate_corpus(failed) == 1
    failure_root = next(failed.artifacts_dir.iterdir())
    evidence = [
        json.loads(line) for line in (failure_root / "rankings.jsonl").read_text().splitlines()
    ]
    assert len([entry for entry in evidence if entry["event"] == "request"]) == 2
    failures = [entry for entry in evidence if entry["event"] == "ranking" and "error" in entry]
    assert len(failures) == 2
    assert all("request" in entry for entry in failures)
    monkeypatch.setattr(assisted, "Ranker", real_ranker)
    corpus["cases"][0]["canonical"]["state"]["x"] += 1
    corrupted = tmp_path / "altered.json"
    corrupted.write_text(json.dumps(corpus))
    with pytest.raises(ValueError, match="do not reproduce"):
        assisted.evaluate_corpus(options(tmp_path / "bad-eval", corpus=corrupted))


def test_provider_failure_has_partial_report_and_no_fallback(tmp_path, monkeypatch):
    real_ranker = assisted.Ranker

    class FailedRanker(real_ranker):
        def __init__(self, provider, *args):
            super().__init__("search")
            self.provider = provider
            self.model = "test"

        def choose(self, canonical, timeout=None, cancelled=lambda: False):
            if self.provider == "zoom":
                raise ProviderError("authentication", "zoom returned HTTP 401")
            return real_ranker("search").choose(canonical)

    monkeypatch.setattr(assisted, "Ranker", FailedRanker)
    forbid_network(monkeypatch)
    assert assisted.episode_run(options(tmp_path, offline=False)) == 1
    root = next(tmp_path.iterdir())
    rows = json.loads((root / "summary.json").read_text())["runs"]
    zoom = next(row for row in rows if row["policy"] == "zoom")
    assert zoom["reason"] == "provider_error"
    assert zoom["game_frames"] == 0
    assert zoom["decisions"] == 0
    assert zoom["api_attempts"] == 1
    assert all(row["decisions"] == 1 for row in rows if row["policy"] != "zoom")
    assert "authentication" in (root / "zoom-001.jsonl").read_text()
    assert assisted.replay(root / "zoom-001.jsonl") == 0


def test_rejects_old_or_incompatible_artifact(tmp_path):
    path = Path(tmp_path) / "direct.jsonl"
    path.write_text('{"decision_index": 1}\n')
    with pytest.raises(ValueError, match="assisted episode"):
        assisted.replay(path)
