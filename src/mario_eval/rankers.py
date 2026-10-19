"""Provider-specific envelopes around identical canonical simulation evidence."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .simulation import rank_outcome

PROMPT_VERSION = "outcome-ranker-v5"
OBJECTIVE = (
    "Choose the candidate that makes progress toward the flag without dying. "
    "Apply priorities in order: completion; survival with a viable next move; then progress. "
    "Never choose a move marked dead when a surviving alternative exists, even if it travels farther. "
    "Avoid a move whose complete seven-follow-up set is all fatal when a viable alternative exists. "
    "Wait or back can be the best move: momentum can carry Mario into danger even while walking. "
    "These are finite-horizon observations, not guarantees of future success. "
    "Unknown outcomes are not evidence of death or safety. "
    "Use continuation_summary to distinguish complete, partial, and untested coverage. "
    "Prefer viable future moves over immediate distance alone; partial fatal follow-ups do not prove a trap. "
    "Among surviving routes, compare progress_summary.best_surviving_two_move_dx and gain_beyond_best_x. "
    "A smaller first move with forward surviving follow-ups can beat a larger move that leaves only waiting or retreat. "
    "Null progress means untested or no observed surviving continuation, not zero progress or proven death. "
    "Use recent_decisions and prior_attempts_without_new_best to avoid repeating an unproductive area/action cycle. "
    "Area matches are approximate: enemies and timing can change; do not ban useful waits or retreats. "
    "Use history to recognize repeated no-progress actions, while allowing useful waits and retreats. "
    "Only your chosen move executes; follow-ups are hypothetical and must be selected on a later decision."
)
URLS = {
    "jev": "https://api.typesafe.ai/v1/systemone",
    "zoom": "https://api.zoom.us/v2/aiservices/decisions/decide",
}
KEYS = {"jev": "TYPESAFE_API_KEY", "zoom": "ZOOM_API_KEY"}


class ProviderError(RuntimeError):
    """Only locally generated messages; never a provider body or credential."""

    def __init__(self, category, detail):
        super().__init__(detail)
        self.category = category


@dataclass
class Ranking:
    candidate: str
    scores: dict
    semantics: str
    latency_ms: float = 0
    metadata: dict = field(default_factory=dict)
    request: dict | None = None


def payload_for(provider, canonical, model="jev-latest", zoom_question="choice"):
    if provider == "jev":
        return {
            "model": model,
            "state": canonical,
            "questions": {
                "action": {
                    "type": "choice",
                    "instructions": OBJECTIVE,
                    "criteria": {
                        key: json.dumps(value, sort_keys=True)
                        for key, value in canonical["outcomes"].items()
                    },
                }
            },
        }
    if provider == "zoom":
        if zoom_question == "choice":
            return {
                "input": json.dumps(canonical, sort_keys=True, allow_nan=False),
                "questions": [
                    {
                        "name": "action",
                        "type": "choice",
                        "instructions": OBJECTIVE,
                        "choices": [
                            {"value": key, "description": json.dumps(value, sort_keys=True)}
                            for key, value in canonical["outcomes"].items()
                        ],
                    }
                ],
            }
        if zoom_question != "predicate":
            raise ValueError("Unsupported Zoom question type")
        return {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(canonical, sort_keys=True, allow_nan=False),
                        }
                    ],
                }
            ],
            "enable_image_input": False,
            "questions": [
                {
                    "name": key,
                    "type": "predicate",
                    "instructions": OBJECTIVE
                    + f" Is candidate '{key}' the best choice among the listed candidates?",
                }
                for key in canonical["outcomes"]
            ],
        }
    raise ValueError("Unsupported provider")


def validate_scores(scores, candidates):
    if not isinstance(scores, dict) or set(scores) != set(candidates):
        raise ProviderError("schema", "Missing or unknown candidate scores")
    for value in scores.values():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ProviderError("schema", "Scores must be finite numbers in [0, 1]")
    return dict(scores)


def parse_ranking(provider, data, candidates, zoom_question="choice"):
    try:
        if not isinstance(data, dict) or not candidates:
            raise ProviderError("schema", "Invalid ranking response or empty candidate set")
        if provider == "zoom" and zoom_question == "choice":
            answers = data["answers"]
            if not isinstance(answers, list) or len(answers) != 1:
                raise ProviderError("schema", "Expected exactly one Zoom action answer")
            answer = answers[0]
            if answer["name"] != "action" or answer["type"] != "choice":
                raise ProviderError("schema", "Expected Zoom action choice answer")
            probabilities = answer["probabilities"]
            if not isinstance(probabilities, list):
                raise ProviderError("schema", "Expected a list of choice probabilities")
            scores = {}
            for entry in probabilities:
                value = entry["value"]
                if not isinstance(value, str) or value in scores:
                    raise ProviderError("schema", "Duplicate or invalid choice value")
                scores[value] = entry["probability"]
            scores = validate_scores(scores, candidates)
            choice = answer["choice"]
            if not isinstance(choice, str) or choice not in candidates:
                raise ProviderError("schema", "Provider selected an unknown candidate")
            # Honor the explicit service selection, including its tie-breaking.
            semantics = "categorical_choice"
        elif provider == "zoom" and zoom_question == "predicate":
            scores = {}
            for answer in data["answers"]:
                name = answer["name"]
                if name in scores or name not in candidates or answer["type"] != "predicate":
                    raise ProviderError(
                        "schema", "Duplicate, unknown, or incorrectly typed candidate"
                    )
                scores[name] = answer["probability"]
            scores = validate_scores(scores, candidates)
            choice = max(candidates, key=lambda key: scores[key])
            semantics = "independent_predicates"
        elif provider == "jev":
            answer = data["answers"]["action"]
            choice = answer["choice"]
            scores = validate_scores(answer["probabilities"], candidates)
            if choice not in candidates:
                raise ProviderError("schema", "Provider selected an unknown candidate")
            semantics = "categorical_choice"
        else:
            raise ProviderError("schema", "Unsupported ranking response mode")
        metadata = {key: data.get(key) for key in ("model", "request_id", "usage")}
        return Ranking(choice, scores, semantics, metadata=metadata)
    except (KeyError, TypeError, AttributeError):
        raise ProviderError(
            "schema", "Response does not match the documented ranking envelope"
        ) from None


class Ranker:
    def __init__(self, provider, timeout=30.0, model="jev-latest", zoom_question="choice"):
        self.provider, self.timeout, self.model = provider, timeout, model
        self.zoom_question = zoom_question
        if provider not in (*URLS, "search", "fixture-jev", "fixture-zoom"):
            raise ValueError("Unknown ranker")
        if provider in KEYS and not os.environ.get(KEYS[provider]):
            raise ProviderError(
                "authentication", f"Configure {KEYS[provider]} before live evaluation"
            )

    def choose(self, canonical, timeout=None, cancelled=lambda: False):
        candidates = tuple(canonical["outcomes"])
        if self.provider not in URLS:
            # Explicit deterministic fixture, never represented as either live model.
            selected = max(candidates, key=lambda key: rank_outcome(canonical["outcomes"][key]))
            return Ranking(
                selected,
                {},
                "deterministic_search" if self.provider == "search" else "offline_fixture",
            )
        payload = payload_for(self.provider, canonical, self.model, self.zoom_question)
        started = time.perf_counter()
        limit = min(self.timeout, timeout) if timeout is not None else self.timeout
        data = bounded_post(self.provider, payload, limit, cancelled)
        ranking = parse_ranking(self.provider, data, candidates, self.zoom_question)
        ranking.latency_ms = (time.perf_counter() - started) * 1000
        ranking.request = payload
        return ranking


def raw_post(provider, payload, timeout):
    """Worker-only HTTP transport. A parent process enforces the total deadline."""
    key = os.environ[KEYS[provider]]
    headers = {"Content-Type": "application/json"}
    headers["Authorization" if provider == "jev" else "x-api-key"] = (
        f"Bearer {key}" if provider == "jev" else key
    )
    request = urllib.request.Request(
        URLS[provider],
        data=json.dumps(payload, allow_nan=False).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise ProviderError(
            "authentication" if exc.code in (401, 403) else "http",
            f"{provider} returned HTTP {exc.code}",
        ) from None
    except (TimeoutError, urllib.error.URLError):
        raise ProviderError(
            "connection_or_timeout", "Request timed out or could not connect"
        ) from None
    except (ValueError, UnicodeError):
        raise ProviderError("schema", "Provider did not return valid JSON") from None


def bounded_post(provider, payload, timeout, cancelled=lambda: False):
    if timeout <= 0:
        raise ProviderError("timeout", "Request budget expired")
    deadline = time.monotonic() + timeout
    # Credentials remain inherited process variables, never argv or the serialized payload.
    process = subprocess.Popen(
        [sys.executable, "-m", "mario_eval.rankers", "--worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    message = json.dumps({"provider": provider, "payload": payload, "timeout": timeout})
    try:
        while True:
            if cancelled():
                raise ProviderError("cancelled", "Request cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError("timeout", "Total request deadline exceeded")
            try:
                output, _ = process.communicate(message, timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                message = None
        if process.returncode:
            raise ProviderError("transport", "Request worker failed")
        envelope = json.loads(output)
        if "error" in envelope:
            raise ProviderError(envelope["error"]["category"], envelope["error"]["detail"])
        return envelope["response"]
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


if __name__ == "__main__":
    try:
        item = json.load(sys.stdin)
        result = {"response": raw_post(item["provider"], item["payload"], item["timeout"])}
    except ProviderError as exc:
        result = {"error": {"category": exc.category, "detail": str(exc)}}
    except Exception:  # noqa: BLE001 — never echo process environment or response bodies
        result = {"error": {"category": "transport", "detail": "Request worker failed"}}
    print(json.dumps(result))
