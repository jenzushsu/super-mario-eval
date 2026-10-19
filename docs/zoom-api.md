# Zoom Decisions reference

Source: JavaScript request, successful JSON response, and Python `requests`
example supplied by the user in chat. No active browser was accessible to this
session and no browser scraping was performed.

Confirmed sample contract:

- POST `https://api.zoom.us/v2/aiservices/decisions/decide`
- `x-api-key: <ZOOM_API_KEY>` and `Content-Type: application/json`
- `input` array containing `role: user`, and a `content` array of `input_text`
  and optionally `input_image` with `image_url` and `detail`.
- `enable_image_input: true` in the supplied image example.
- `questions` array with `name`, `instructions`, and `type: predicate`.
- Response `answers` array with matching `name`, `type: predicate`, and numeric
  `probability`. Additional top-level `model`, `request_id`, and `usage` metadata.

The response example used probability `0.9835969681250021`, model
`zoom-decisions`, and usage with `input_units`, `output_units`, `unit_type`, and
`details.cached_input_tokens`.

The Python sample posts a decoded JSON object using `requests.post(..., json=...)`.
The implementation uses the standard library's `urllib.request` to send the same
JSON and headers, with a 30-second timeout and normal proxy/TLS handling.
No undocumented SDK or native choice schema is assumed.

Mario adaptation: serialize the shared state as input_text, set
`enable_image_input: false`, and submit seven named action predicates together.
Choose the largest raw probability. Reject missing, duplicate, incorrectly typed,
nonfinite, or out-of-range action scores. Do not normalize or synthesize confidence.

Still unverified without a real key: text-only requests, seven predicates in a
single call, service limits and authenticated responses in this cloud environment.
A native choice sample, if provided later, could replace predicate ranking and
make action-selection semantics closer to Jev's Choice.
