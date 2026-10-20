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
        "history": {
            "recent_controls": [{"action": "right", "frames": 52, "dx": 0}],
            "frames_since_best_x": 52,
        },
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
            "choices": [
                {"value": key, "description": json.dumps(value, sort_keys=True)}
                for key, value in canonical["outcomes"].items()
            ],
        }
        assert {c["value"]: c["description"] for c in question["choices"]} == payload_for(
            "jev", canonical
        )["questions"]["action"]["criteria"]
        return expected

    monkeypatch.setattr("mario_eval.rankers.bounded_post", respond)
    result = Ranker("zoom").choose(canonical)
    assert result.candidate == "jump"
    assert result.scores == {"run": 0.1, "jump": 0.9}
    assert result.semantics == "categorical_choice"
    assert result.metadata == {k: expected[k] for k in ("model", "request_id", "usage")}
    assert result.request["questions"][0]["type"] == "choice"
    from mario_eval.rankers import request_contract_fingerprint

    assert result.request_contract_sha256 == request_contract_fingerprint("zoom", result.request)


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


def test_matching_request_fingerprints_cover_input_order_objective_and_controls(canonical):
    import copy

    from mario_eval.rankers import request_contract_fingerprint

    jev = payload_for("jev", canonical)
    zoom = payload_for("zoom", canonical)
    assert set(jev) == {"model", "state", "questions"}
    assert set(zoom) == {"input", "questions", "model"}
    expected = request_contract_fingerprint("jev", jev)
    assert request_contract_fingerprint("zoom", zoom) == expected
    extra = copy.deepcopy(jev)
    extra["questions"]["additional"] = {"type": "predicate", "instructions": "Extra task"}
    assert request_contract_fingerprint("jev", extra) != expected
    assert (
        request_contract_fingerprint(
            "zoom", payload_for("zoom", canonical, zoom_question="predicate")
        )
        != expected
    )
    for change in ("state", "instructions", "order", "description", "temperature"):
        altered = copy.deepcopy(zoom)
        if change == "state":
            state = json.loads(altered["input"])
            state["state"]["x"] += 1
            altered["input"] = json.dumps(state)
        elif change == "instructions":
            altered["questions"][0]["instructions"] = "Different objective"
        elif change == "order":
            altered["questions"][0]["choices"].reverse()
        elif change == "description":
            altered["questions"][0]["choices"][0]["description"] = "{}"
        else:
            altered["temperature"] = 0
        assert request_contract_fingerprint("zoom", altered) != expected


def test_comparison_settings_do_not_claim_unknown_model_defaults_match():
    from mario_eval.rankers import comparison_parameters

    config = {
        "model_requested": "jev-1.13.0",
        "zoom_question": "choice",
        "track": "episodes",
        "seed": 123,
        "limits": {"timeout": 30},
    }
    result = comparison_parameters(config)
    assert result["question_formats_match"]
    assert result["decoding_parameters_sent"] == {"jev": {}, "zoom": {}}
    assert not result["service_decoding_equivalence_verified"]
    assert not result["identical_state_evaluation"]
    assert result["model_selection"]["jev"] == "jev-1.13.0"
    assert result["shared_evaluation_settings"]["seed"] == 123
    config.update(zoom_question="predicate", track="identical_states")
    result = comparison_parameters(config)
    assert not result["question_formats_match"]
    assert result["identical_state_evaluation"]


@pytest.mark.parametrize("model", ["zoom-decisions", "zoom-decisions-pro"])
@pytest.mark.parametrize("question", ["choice", "predicate"])
def test_zoom_model_payload(model, question, canonical):
    from mario_eval.rankers import request_contract_fingerprint

    payload = payload_for("zoom", canonical, zoom_question=question, zoom_model=model)
    assert payload["model"] == model
    baseline = payload_for("zoom", canonical, zoom_question=question)
    assert request_contract_fingerprint("zoom", payload) == request_contract_fingerprint(
        "zoom", baseline
    )
    assert payload_for("jev", canonical, zoom_model=model)["model"] == "jev-latest"


def test_zoom_pro_roundtrip_and_wrong_model_rejected(canonical, monkeypatch):
    monkeypatch.setenv("ZOOM_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv("ZOOM_API_KEY", raising=False)
    response = choice_response()
    response["model"] = "zoom-decisions-pro"

    def respond(provider, payload, limit, cancelled):
        assert payload["model"] == "zoom-decisions-pro"
        return response

    monkeypatch.setattr("mario_eval.rankers.bounded_post", respond)
    ranker = Ranker("zoom", zoom_model="zoom-decisions-pro")
    assert ranker.choose(canonical).metadata["model"] == "zoom-decisions-pro"
    response["model"] = "zoom-decisions"
    with pytest.raises(ProviderError) as error:
        ranker.choose(canonical)
    assert error.value.category == "model_mismatch"


def test_zoom_authentication_precedence(monkeypatch):
    from mario_eval.rankers import authentication_headers

    monkeypatch.setenv("ZOOM_API_KEY", "legacy-key")
    monkeypatch.setenv("ZOOM_ACCESS_TOKEN", "access-token")
    headers = authentication_headers("zoom")
    assert headers["Authorization"] == "Bearer access-token"
    assert "x-api-key" not in headers
    monkeypatch.delenv("ZOOM_ACCESS_TOKEN")
    headers = authentication_headers("zoom")
    assert headers["x-api-key"] == "legacy-key"
    assert "Authorization" not in headers
