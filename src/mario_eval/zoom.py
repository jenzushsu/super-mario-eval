from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence

from typesafe_mario.actions import ACTION_DESCRIPTIONS, Action
from typesafe_mario.policy import Decision
from typesafe_mario.state import MarioSnapshot

URL = "https://api.zoom.us/v2/aiservices/decisions/decide"


def build_payload(state: Mapping, actions: Sequence[Action]) -> dict:
    """Use only the predicate schema demonstrated by the supplied Zoom sample."""
    if not actions:
        raise ValueError("At least one legal action is required")
    return {
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(state, allow_nan=False),
                    }
                ],
            }
        ],
        "enable_image_input": False,
        "questions": [
            {
                "name": action.value,
                "type": "predicate",
                "instructions": (
                    "Goal: reach the stage flag while avoiding death. "
                    "Given this structured Mario state, is "
                    + action.value
                    + " the best controller macro for the next decision? "
                    + ACTION_DESCRIPTIONS[action]
                    + " Compare with these legal actions: "
                    + ", ".join(a.value for a in actions)
                    + ". Use terrain reliability, trajectory, projected hazards and recent control. "
                    "Preserve forward motion over a known gap; jump before the projected deadline. "
                    "The action duration is in reaction_timing; the world pauses during inference."
                ),
            }
            for action in actions
        ],
    }


def parse_response(response: dict, actions: Sequence[Action], latency_ms: float) -> Decision:
    expected = {action.value for action in actions}
    scores = {}
    for answer in response.get("answers", []):
        name = answer.get("name")
        if name not in expected:
            continue
        value = answer.get("probability")
        if name in scores or answer.get("type") != "predicate":
            raise ValueError("Zoom returned a duplicate or incorrectly typed action answer")
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError("Zoom action probability must be numeric")  # noqa: TRY004 — invalid API data
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Zoom action probability must be finite and between zero and one")
        scores[name] = float(value)
    if not expected or scores.keys() != expected:
        raise ValueError("Zoom omitted one or more legal action answers")
    # Stable ties follow the shared legal action order. Never normalize predicates.
    action = max(actions, key=lambda candidate: scores[candidate.value])
    return Decision(action, scores[action.value], scores, latency_ms)


class ZoomAPIError(RuntimeError):
    """A diagnostic assembled locally, never from a provider response body."""


class ZoomPolicy:
    def __init__(self, timeout: float = 30) -> None:
        self.key = os.environ.get("ZOOM_API_KEY")
        if not self.key:
            raise RuntimeError("ZOOM_API_KEY is required; configure it in environment settings")
        self.timeout = timeout
        self.last_metadata = {}

    def choose(self, snapshot: MarioSnapshot, actions: Sequence[Action]) -> Decision:
        request = urllib.request.Request(
            URL,
            data=json.dumps(build_payload(snapshot.to_state(), actions)).encode(),
            headers={"x-api-key": self.key, "Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as result:
                response = json.load(result)
        except urllib.error.HTTPError as exc:
            # Do not log server bodies, which may echo input or credentials.
            raise ZoomAPIError(f"Zoom Decisions returned HTTP {exc.code}") from None
        except urllib.error.URLError:
            raise ZoomAPIError(
                "Zoom Decisions connection failed; check access and connectivity"
            ) from None
        latency = (time.perf_counter() - started) * 1000
        try:
            decision = parse_response(response, actions, latency)
        except ValueError as exc:
            raise ZoomAPIError(str(exc)) from None
        self.last_metadata = {key: response.get(key) for key in ("model", "request_id", "usage")}
        return decision
