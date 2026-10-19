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

## Parallel episode scheduling

Direct and assisted episode lanes now request decisions and execute independently.
The expanded suite passes **49 tests**, including checks that one lane executes a
move and submits its next decision while the other is still waiting, cancellation
joins workers before cleanup, desktop rendering stays on the main thread, and
concurrent assisted trajectories replay without state contamination. Both desktop
modes passed offline SDL smoke runs; screenshots were inspected. No additional
live provider calls were made for this scheduling change.

## Seven-move continuation coverage and shared history (2026-10-20)

The `all-seven-v1` configuration tests every available follow-up move for each
surviving candidate. `outcome-ranker-v3` sends both providers the same explicit
coverage/survival summaries and reconstructed recent-control/no-progress history.
There are no automatic move overrides. Old episode replay remains supported;
old corpora require recapture because canonical evidence changed.

- Full suite: **69 passed**, including five compressed action-prefix regression
  fixtures from uploaded runs (two Zoom traps, Jev/Zoom wait escapes, and a Zoom
  retreat). Fixtures contain controls and fingerprints, no credentials or ROM data.
- Full coverage reproduces fatal continuations in the trap fixtures while finding
  the previously omitted surviving wait in both escape fixtures. Lookahead restores
  history; replay prefixes reconstruct it without contamination from simulation.
- Offline search on World 1-1, seed 123: reached x=2227, then stalled at 27 decisions
  and 1512 actual frames. Report counts seven non-forward selections, six repeated
  no-progress selections. This improves on the earlier baseline's x=2010 death but
  does not demonstrate level completion or live model improvement.
- Three newly captured checkpoints passed offline identical-state evaluation;
  the new 1512-frame trajectory replayed successfully.
- An older uploaded winning Zoom log still replays 2187 frames with zero API calls.
- Formatting, lint, and whitespace checks passed. No paid calls were made for this
  change; new live Jev/Zoom outcomes remain to be measured on the revised evidence.

## Continuous real-time playback (2026-10-20)

- Removed the assisted display's 20 FPS cap. Rendering and playback use deadline
  pacing targeting 60 FPS; the paused-mode SDL smoke measured a median draw
  interval of 16.7 ms. Slow frames do not cause emulator-frame skipping.
- Added a separate `realtime` track with live emulators and isolated planning
  emulators. Neutral controls bootstrap the first decision; selected moves then
  continue during inference. Decision ages and discarded replies are recorded.
- **75 tests passed**, including gameplay advancement during blocked inference,
  cancellation/cleanup, stale decision ages, held jump release, provider failure
  isolation, and replay of real-time control sequences.
- Both direct and assisted desktop smoke runs passed. The real-time SDL smoke
  completed two fixture decisions per lane; the first lane's 165-frame trajectory
  replayed successfully. Its screenshot was inspected. These are offline checks,
  not evidence of live model performance or level completion.
- `--depth 0` is documented for lower planning latency. Full continuation search
  remains available via `--depth 1`. Real-time results must remain separate from
  paused assisted comparisons because latency changes the game state.
