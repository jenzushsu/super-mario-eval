# Zoom Decisions reference

Source: user-supplied predicate, choice, score, and mixed-question requests and
successful response JSON. These are observed examples, not a complete service
specification. No browser scraping was performed.

All examples POST to `https://api.zoom.us/v2/aiservices/decisions/decide` with
`x-api-key: <ZOOM_API_KEY>` and `Content-Type: application/json`. Inputs can be
plain text strings. The image example uses a user message/content array containing
`input_text` and `input_image`, plus `enable_image_input: true`.

## Native choice (default for assisted mode)

```json
{
  "input": "<serialized shared Mario state and simulated outcomes>",
  "questions": [{
    "name": "action",
    "type": "choice",
    "instructions": "<shared objective also sent to Jev>",
    "choices": [
      {"value": "run", "description": "<serialized run outcome and continuations>"},
      {"value": "jump", "description": "<serialized jump outcome and continuations>"}
    ]
  }]
}
```

The actual runner lists all seven candidates. Choice descriptions bind each label
to its measured outcome and continuations, using exactly the same JSON as Jev
criteria. The shared canonical input remains identical. Description support comes
from the supplied mixed-question example.

The response contains `answers: [{"name": "action", "type": "choice",
"choice": "jump", "probabilities": [{"value": "run", "probability": 0.1},
{"value": "jump", "probability": 0.9}]}]`, plus `model`, `request_id`, and `usage`.
The adapter honors the explicit `choice`, including service tie-breaking. It
requires exactly one matching answer and a complete, unique candidate probability
list; values must be finite numbers in [0, 1]. It preserves raw scores without
renormalization or assuming cross-provider calibration.

Run locally:

```sh
uv run --frozen --env-file .env mario-eval assisted --zoom-question choice --episodes 1 --max-decisions 100 --wall-seconds 600
```

`choice` is the default for `assisted` and `evaluate`. To reproduce the older
predicate experiment, pass `--zoom-question predicate`. The selected type is
saved in config.json and the exact request and score semantics are logged.
Both modes preserve the same canonical evidence, candidates, and objective.
The request version is `outcome-ranker-v4`; old logs retain their original version.
Direct control (`mario-eval` without a subcommand) retains its predicate adapter.

## Predicate

A question has `name`, `instructions`, and `type: predicate`. Its answer has the
same name/type and a numeric `probability`. The legacy adapter submits one question
per candidate, selects the highest raw probability, and uses candidate order to
break ties. These independent scores are not a categorical distribution.

## Score

A question has `type: score` and an ordered `levels` array of `{label, description}`.
The supplied three-level example returns:

```json
{
  "type": "score",
  "name": "Severity",
  "score": 1.0001911501845375,
  "probabilities": [
    {"value": 0, "probability": 0.0012174912130035202},
    {"value": 1, "probability": 0.9973738673894552},
    {"value": 2, "probability": 0.0014086413975412054}
  ]
}
```

In both supplied score responses, `score` matches the probability-weighted mean
of the zero-based level indices. It is fractional, not a probability or a label
index to round blindly. General limits and service guarantees remain undocumented.

## Mixed questions and validation status

Predicate, choice, and score questions can share a request. The supplied mixed
response returns a named/typed answer for each question. Any future mixed adapter
should match by name and type rather than rely on response order. The current
assisted comparison asks both services only for an action choice; score and
predicate diagnostics are documented but not added to that task.

User-uploaded gameplay logs demonstrate successful seven-predicate calls. Native
choice parsing is tested against the supplied response structure; improved Mario
performance with native choice remains unverified. Earlier cloud calls returned
HTTP 403, while user-local calls succeeded. No credentials are stored in this repo.

Requests use standard-library urllib in a subprocess with a total deadline,
normal proxy/TLS handling, and no retries. Request bodies are logged without
authentication headers, alongside model/request ID/usage when available. Usage
units and cache details are preserved as returned; monetary cost is unknown.
