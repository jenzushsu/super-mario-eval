# Zoom survival review: nine archived runs

Source: user-supplied `artifacts.zip`, runs `20261019T163239Z-dbe18c82`
through `20261019T164727Z-d42b42c4`. All nine Zoom action logs replayed with
matching state fingerprints and no API calls.

All configurations use paused assisted episodes, native Zoom choice, seed 123,
48-frame macros, depth 1, `all-seven-v1`, and `outcome-ranker-v3`.
They record commit `a9739e2` with a dirty working tree. This is not real-time
playback: API latency does not advance the emulator.

## Results

| Run time (UTC) | Zoom result / best x | Jev result / best x |
| --- | --- | --- |
| 16:32:39 | Died / 2466 | Stalled / 2403 |
| 16:34:24 | Died / 2022 | Cancelled / 2403 |
| 16:35:38 | Died / 1666 | Cancelled / 2148 |
| 16:36:37 | Died / 2757 | Stalled / 2403 |
| 16:38:34 | Died / 2472 | Cancelled / 2402 |
| 16:43:33 | Died / 1666 | Cancelled / 2281 |
| 16:44:43 | Died / 2472 | Cancelled / 2403 |
| 16:46:18 | Died / 1666 | Cancelled / 2356 |
| 16:47:27 | Died / 1666 | Cancelled / 2226 |

Zoom completed 0/9, with median best x 2022. Jev stalled twice and was cancelled
seven times. Search stalled seven times at best x 2227 and was cancelled twice.
No provider errors were recorded. Five episodes were configured per invocation,
but only attempt 1 is present in each directory. These are repeated starts on
the same seed, not nine completed five-episode comparisons. Cancelled runs do
not establish failure or a fair provider win-rate comparison.

## Three recurring causes

1. **Five deaths despite an immediately surviving alternative.** Four runs reach
   x1581, where Zoom chooses `walk` even though it is explicitly marked `dead`.
   `wait` and `back` survive and retain surviving follow-ups. One run makes the
   same mistake at x2680. This is a ranking problem, not insufficient API speed.
2. **Three deaths following missing airborne lookahead.** At x2370, Zoom selects
   `run_jump` (+77, unknown, zero follow-ups) instead of `jump` (+63, alive,
   surviving next jump). At the next state, all seven moves die. Expanding the
   unknown endpoint reproduces all seven fatal continuations before committing
   to that move. The old report incorrectly shows zero incomplete follow-ups
   because that diagnostic excludes unknown outcomes.
3. **One death after a known finite-horizon trap.** At x1842, Zoom selects
   `run_jump` (+169) despite all seven tested follow-ups being fatal. `walk` and
   `hop` (+90) have surviving jumps. The extra immediate distance is misleading.

## Changes and local evidence

- `all-seven-airborne-v2` expands nonterminal unknown endpoints under the same
  simulation/frame/deadline budgets. Terminal/truncated states are not stepped.
  Existing v1 corpora retain their original expansion behavior.
- `outcome-ranker-v4` explicitly prioritizes survival before distance and allows
  waiting/retreating. Zoom choice descriptions carry the same outcome evidence
  as Jev criteria; neither receives extra hidden information.
- Optional `--survival-guard` replaces predicted death or a completely tested
  all-fatal next-move set only when an evaluated surviving alternative exists.
  It prefers completion, then the provider's score among eligible alternatives.
  This shared rule applies to all lanes in paused assisted episodes. It is off
  by default and unavailable for stale real-time predictions.
- Original rankings and probabilities remain intact. Separate guard events,
  execution sources, and report counts disclose every replacement. Unknown
  outcomes and incomplete coverage are now counted explicitly.

Four credential-free regression fixtures reconstruct the exact failure states
from recorded controller actions and verify their fingerprints. Using the saved
Zoom probabilities, the guard selects:

| State x | Original choice | Replacement | Immediate endpoint |
| --- | --- | --- | --- |
| 1581 | walk (dead) | wait | alive at 1619 |
| 1842 | run_jump (all follow-ups fatal) | hop | alive at 1932 |
| 2370 | run_jump (unknown, newly exposed all-fatal follow-ups) | jump | alive at 2433 |
| 2680 | walk (dead) | back | alive at 2649 |

The tests also execute a surviving follow-up after each replacement. This proves
local escape from the recorded traps within the available macros, not eventual
stage completion. Later choices can still die or stall. It is not valid to replay
the remaining original scores after a replacement, because the state has changed.

A live v4 Zoom request from the cloud environment returned HTTP 403. Consequently,
no new live-provider win rate or prompt improvement has been measured here.

## Recommended local evaluation

With both keys in `.env`:

```sh
uv run --frozen --env-file .env mario-eval assisted --zoom-question choice --depth 1 --survival-guard --episodes 5 --max-decisions 100 --wall-seconds 600 --simulation-frames 400000 --headless
```

Remove `--headless` to watch. Let all five attempts finish. The higher simulation
budget accommodates airborne expansion; no completion is guaranteed. Keep
`choice`: the observed failures concern survival ranking, not a demonstrated
advantage for independent predicates.

For a model-only baseline, run the same command without `--survival-guard` and
keep the artifact directories separate. Compare completed attempts, deaths,
stalls, best x, and override counts. Label guarded completions as provider plus
guard; they are not evidence that the provider itself stopped making fatal
choices. Do not combine real-time and paused results.
