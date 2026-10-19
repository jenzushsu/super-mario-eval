import io
import json
import math
import urllib.error

import pytest

from mario_eval.rankers import ProviderError, Ranker, parse_ranking, payload_for, raw_post


@pytest.fixture
def canonical():
    return {
        "state": {"x": 40},
        "outcomes": {
            "run": {"status": "dead", "dx": 100, "continuations": []},
            "jump": {"status": "alive", "dx": 80, "continuations": []},
        },
    }


def test_canonical_content_identical_between_envelopes(canonical):
    jev = payload_for("jev", canonical)
    zoom = payload_for("zoom", canonical, zoom_question="predicate")
    assert jev["state"] == json.loads(zoom["input"][0]["content"][0]["text"])
    assert set(jev["questions"]["action"]["criteria"]) == {q["name"] for q in zoom["questions"]}


def test_choice_and_predicate_semantics(canonical):
    candidates = tuple(canonical["outcomes"])
    jev = parse_ranking(
        "jev",
        {"answers": {"action": {"choice": "jump", "probabilities": {"run": 0.1, "jump": 0.9}}}},
        candidates,
    )
    zoom = parse_ranking(
        "zoom",
        {
            "answers": [
                {"name": "run", "type": "predicate", "probability": 0.6},
                {"name": "jump", "type": "predicate", "probability": 0.7},
            ]
        },
        candidates,
        zoom_question="predicate",
    )
    assert jev.candidate == zoom.candidate == "jump"
    assert jev.semantics != zoom.semantics
    assert sum(zoom.scores.values()) > 1


@pytest.mark.parametrize(
    "scores",
    [
        {},
        {"run": 1},
        {"run": 0.5, "jump": 0.5, "extra": 0},
        {"run": math.nan, "jump": 0.5},
        {"run": True, "jump": 0},
        {"run": -1, "jump": 2},
        {"run": "0", "jump": 1},
    ],
)
def test_rejects_bad_choice_scores(scores):
    with pytest.raises(ProviderError):
        parse_ranking(
            "jev",
            {"answers": {"action": {"choice": "jump", "probabilities": scores}}},
            ("run", "jump"),
        )


@pytest.mark.parametrize(
    "answers",
    [
        [],
        [{"name": "run", "type": "predicate", "probability": 0.5}] * 2,
        [{"name": "unknown", "type": "predicate", "probability": 0.5}],
        [{"name": "run", "type": "choice", "probability": 0.5}],
    ],
)
def test_rejects_missing_duplicate_unknown_and_type(answers):
    with pytest.raises(ProviderError):
        parse_ranking("zoom", {"answers": answers}, ("run", "jump"), "predicate")


def test_ties_stable_and_search_prefers_survival(canonical, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("Offline rankers must not make HTTP requests")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    for name in ("search", "fixture-jev", "fixture-zoom"):
        assert Ranker(name).choose(canonical).candidate == "jump"
    tied = {
        "answers": [
            {"name": k, "type": "predicate", "probability": 0.5} for k in canonical["outcomes"]
        ]
    }
    assert parse_ranking("zoom", tied, tuple(canonical["outcomes"]), "predicate").candidate == "run"


@pytest.mark.parametrize("provider", ["jev", "zoom"])
def test_http_errors_sanitized(provider, canonical, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-secret")
    monkeypatch.setenv("ZOOM_API_KEY", "test-secret")

    def fail(request, timeout):
        assert timeout <= 2
        assert request.get_method() == "POST"
        raise urllib.error.HTTPError(request.full_url, 401, "test-secret", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ProviderError, match="returned HTTP 401") as error:
        raw_post(provider, payload_for(provider, canonical), 2)
    assert "test-secret" not in str(error.value)
    assert error.value.category == "authentication"


@pytest.mark.parametrize("failure", ["timeout", "json", "shape"])
def test_timeout_and_malformed_response(canonical, monkeypatch, failure):
    monkeypatch.setenv("ZOOM_API_KEY", "test-secret")

    def respond(*args, **kwargs):
        if failure == "timeout":
            raise TimeoutError()
        return io.BytesIO(b"not json" if failure == "json" else b'{"answers":null}')

    monkeypatch.setattr("urllib.request.urlopen", respond)
    with pytest.raises(ProviderError):
        data = raw_post("zoom", payload_for("zoom", canonical), 2)
        parse_ranking("zoom", data, tuple(canonical["outcomes"]))


def test_total_deadline_kills_stalled_worker(monkeypatch):
    import subprocess
    import sys
    import time

    from mario_eval.rankers import bounded_post

    original = subprocess.Popen
    workers = []

    def stall(*args, **kwargs):
        process = original([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        workers.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", stall)
    started = time.monotonic()
    with pytest.raises(ProviderError, match="deadline"):
        bounded_post("zoom", {}, 0.2)
    assert time.monotonic() - started < 3
    assert workers[0].poll() is not None


def test_cancellation_kills_worker(monkeypatch):
    import subprocess
    import sys

    from mario_eval.rankers import bounded_post

    original = subprocess.Popen
    workers = []

    def stall(*args, **kwargs):
        process = original([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        workers.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", stall)
    with pytest.raises(ProviderError, match="cancelled"):
        bounded_post("zoom", {}, 30, lambda: True)
    assert workers[0].poll() is not None


def choice_response():
    return {
        "answers": [
            {
                "name": "action",
                "type": "choice",
                "choice": "jump",
                "probabilities": [
                    {"value": "run", "probability": 0.1},
                    {"value": "jump", "probability": 0.9},
                ],
            }
        ],
        "model": "zoom-decisions",
        "request_id": "test-request",
        "usage": {"input_units": 113, "output_units": 1, "unit_type": "tokens"},
    }


def test_native_choice_envelope_and_roundtrip(canonical, monkeypatch):
    monkeypatch.setenv("ZOOM_API_KEY", "test-key")
    expected = choice_response()

    def respond(provider, payload, limit, cancelled):
        assert provider == "zoom"
        assert json.loads(payload["input"]) == canonical
        (question,) = payload["questions"]
        assert question == {
            "name": "action",
            "type": "choice",
            "instructions": payload_for("jev", canonical)["questions"]["action"]["instructions"],
            "choices": [{"value": key} for key in canonical["outcomes"]],
        }
        return expected

    monkeypatch.setattr("mario_eval.rankers.bounded_post", respond)
    result = Ranker("zoom").choose(canonical)
    assert result.candidate == "jump"
    assert result.scores == {"run": 0.1, "jump": 0.9}
    assert result.semantics == "categorical_choice"
    assert result.metadata == {k: expected[k] for k in ("model", "request_id", "usage")}
    assert result.request["questions"][0]["type"] == "choice"


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "unknown",
        "nan",
        "bool",
        "range",
        "wrong_name",
        "wrong_type",
        "unknown_choice",
        "extra_answer",
    ],
)
def test_native_choice_rejects_malformed_answers(fault):
    response = choice_response()
    answer = response["answers"][0]
    if fault == "missing":
        answer["probabilities"].pop()
    elif fault == "duplicate":
        answer["probabilities"].append(answer["probabilities"][0])
    elif fault == "unknown":
        answer["probabilities"][0]["value"] = "fly"
    elif fault in ("nan", "bool", "range"):
        answer["probabilities"][0]["probability"] = {"nan": math.nan, "bool": True, "range": 1.1}[
            fault
        ]
    elif fault == "wrong_name":
        answer["name"] = "unrequested"
    elif fault == "wrong_type":
        answer["type"] = "score"
    elif fault == "unknown_choice":
        answer["choice"] = "fly"
    else:
        response["answers"].append(dict(answer))
    with pytest.raises(ProviderError):
        parse_ranking("zoom", response, ("run", "jump"))


def test_native_choice_preserves_service_tie_selection():
    response = choice_response()
    for item in response["answers"][0]["probabilities"]:
        item["probability"] = 0.5
    assert parse_ranking("zoom", response, ("run", "jump")).candidate == "jump"
