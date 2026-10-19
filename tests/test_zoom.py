import math

import pytest
from typesafe_mario.actions import Action

from mario_eval.zoom import build_payload, parse_response

ACTIONS = tuple(Action)


def response():
    return {
        "answers": [
            {
                "name": a.value,
                "type": "predicate",
                "probability": 0.8 if a == Action.RIGHT_RUN_JUMP else 0.3,
            }
            for a in ACTIONS
        ]
    }


def test_payload_uses_supplied_text_predicate_contract():
    payload = build_payload({"player": {"x": 40}}, ACTIONS)
    assert payload["enable_image_input"] is False
    assert payload["input"][0]["content"][0]["type"] == "input_text"
    assert {q["name"] for q in payload["questions"]} == {a.value for a in ACTIONS}
    assert all(q["type"] == "predicate" for q in payload["questions"])


def test_selects_max_without_normalizing_independent_probabilities():
    decision = parse_response(response(), ACTIONS, 42)
    assert decision.action == Action.RIGHT_RUN_JUMP
    assert decision.confidence == 0.8
    assert sum(decision.probabilities.values()) > 1
    assert decision.latency_ms == 42


@pytest.mark.parametrize("value", [math.nan, math.inf, -0.1, 1.1, True, "0.8", None])
def test_rejects_invalid_probability(value):
    data = response()
    data["answers"][0]["probability"] = value
    with pytest.raises(ValueError):
        parse_response(data, ACTIONS, 1)


def test_rejects_missing_answer():
    data = response()
    data["answers"].pop()
    with pytest.raises(ValueError):
        parse_response(data, ACTIONS, 1)


def test_rejects_duplicate_answer():
    data = response()
    data["answers"].append(data["answers"][0])
    with pytest.raises(ValueError):
        parse_response(data, ACTIONS, 1)


def test_tie_is_stable():
    data = response()
    for answer in data["answers"]:
        answer["probability"] = 0.5
    assert parse_response(data, ACTIONS, 1).action == ACTIONS[0]


def test_request_headers_body_and_metadata(monkeypatch):
    import io
    import json

    from mario_eval.zoom import URL, ZoomPolicy

    monkeypatch.setenv("ZOOM_API_KEY", "test-placeholder")
    data = response() | {
        "model": "zoom-decisions",
        "request_id": "test-id",
        "usage": {"output_units": 7},
    }
    captured = {}

    def open_request(request, timeout):
        captured["request"] = request
        assert timeout == 30
        return io.BytesIO(json.dumps(data).encode())

    class Snapshot:
        def to_state(self):
            return {"player": {"x": 40}}

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    policy = ZoomPolicy()
    assert policy.choose(Snapshot(), ACTIONS).action == Action.RIGHT_RUN_JUMP
    request = captured["request"]
    assert request.full_url == URL
    assert request.get_method() == "POST"
    assert request.get_header("X-api-key") == "test-placeholder"
    assert json.loads(request.data)["input"][0]["content"][0]["type"] == "input_text"
    assert policy.last_metadata["request_id"] == "test-id"


def test_http_error_does_not_echo_response_body(monkeypatch):
    import urllib.error

    from mario_eval.zoom import ZoomPolicy

    monkeypatch.setenv("ZOOM_API_KEY", "test-placeholder")

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.zoom.us", 401, "secret body", {}, None)

    class Snapshot:
        def to_state(self):
            return {}

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(RuntimeError, match="^Zoom Decisions returned HTTP 401$"):
        ZoomPolicy().choose(Snapshot(), ACTIONS)
