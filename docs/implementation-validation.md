# FR-001 implementation validation

Validated on 2026-10-19 with Python 3.13 and the frozen dependencies in uv.lock.
The implementation follows the methodology reviewed in [reference-evaluation.md](reference-evaluation.md), without copying the reference implementation.

- `python -m pytest -q`: **45 passed**. Coverage includes native snapshot restoration,
  candidate-order independence, simulation/execution parity, strict adapter parsing,
  total request deadlines/cancellation, identical-state evidence, failure logging,
  shared validation budgets, and tampered replay detection.
- `ruff check src tests`, formatting, and `git diff --check`: passed.
- Offline assisted World 1-1: three attempts per fixture/search policy, three decisions
  per attempt, nine report rows. All reached the decision cap at x=434; no API calls.
- Offline depth-one capture: 12 decisions, x=1497, decision cap; 13 captured states
  cover grounded, airborne, enemy, obstacle, gap, and open scene tags. These are
  trajectory-derived tags, not an exhaustive benchmark or a completed level.
- Frozen-state evaluation passed on three captured states. Replay verified 294 actual
  frames without API calls; the integration suite also verifies replay and corruption
  rejection. Shared reconstruction work is counted once in JSON and Markdown.
- Desktop screenshot inspected: assisted label, level/seed, separate provider panels,
  progress/status, and final run status are visible.
- Bounded live smoke: **Jev HTTP 403; Zoom HTTP 403**, one attempt per service, zero
  successful decisions. Search completed its bounded decision independently. No
  provider fallback was substituted. Both integrations remain unverified pending
  provider access; Zoom's multi-predicate behavior still needs a successful live test.

Offline fixtures use deterministic ranking and are not model results. No claim of
model superiority, successful live gameplay, or level completion follows from these
checks. Generated artifacts remain local under the ignored `artifacts/` directory.
See the [README](../README.md) for reproducible local commands and secret setup.
