# FR-001: Compare Jev and Zoom Decisions using simulated Mario outcomes

Status: Implemented; offline validation passed; live integration blocked by HTTP 403

Priority: High  
Project: `jenzushsu/super-mario-eval`

## Problem

The current side-by-side comparison frequently stalls or ends in early deaths.
Those outcomes mix model decisions with observation accuracy, jump timing, and
controller behavior, making it difficult to understand differences between the
services. Existing logs require manual inspection and do not distinguish model
quality from assistance provided by the harness.

The reference [4esv/jev-mario](https://github.com/4esv/jev-mario), reviewed at
`8459bbb476c73463d9d3389639c158ecca4e21b4`, reports stronger gameplay when Jev ranks
simulated outcomes. Its direct-control runs still die early. Our
[reference evaluation](../reference-evaluation.md) documents the code, archived
results, and offline checks; its successful API runs have not been independently
reproduced here.

## Desired result

Add an explicitly labeled **assisted outcome-ranking** mode. The emulator explores
candidate moves, describes their measured consequences, and lets Jev, Zoom, or a
search-only baseline choose among the same options. Users can compare decisions
on identical saved states and inspect separate full-episode results.

Keep existing direct control as a separate mode. Never combine the two modes into
one leaderboard or present assisted completion as unaided model gameplay.

## Scope

| Included in the first release | Outside the first release |
| --- | --- |
| World 1-1, with an extensible level configuration | A promise of level completion or model superiority |
| Jev, Zoom, and deterministic search-only policies | Model training or prompt tuning on evaluation outcomes |
| Shared outcome simulation and macro executor | Real-time latency-sensitive control |
| Identical-state evaluation and independent episodes | Hosted deployment or a browser UI rewrite |
| Local desktop comparison and headless evaluation | Automatic adoption of reference-specific springboard tricks |
| Readable reports, JSONL evidence, and offline replay | Bundling ROMs or provider credentials |

## Functional requirements

### FR-01 — Shared simulator

- Define a versioned candidate action set, macro durations, landing/settling rules,
  continuation depth, and maximum simulation budget. Use the same configuration
  for all three policies and persist it with each run.
- Snapshot complete relevant emulator and wrapper state, explore each candidate,
  and restore the original state before exploring another or executing a choice.
- Candidate outcomes include survival, completion, actual frames simulated,
  displacement, landing status, and surviving continuation counts. Report horizon
  exhaustion or unknown outcomes explicitly; do not silently equate them to death.
- Execute a selected macro through the same code used for simulation. Preserve
  jump-button release semantics and count actual emulator steps.
- Start with simple shared macros. Introduce additional hand-tuned moves only as
  a separately versioned action set applied to every policy.

### FR-02 — Provider adapters and control baseline

- Give both services the same canonical state and outcome descriptions, candidate
  IDs, and objective. Preserve the exact serialized requests for inspection after
  removing authentication data.
- Jev uses native Choice. Zoom initially ranks independent predicates using the
  supplied request/response contract. Clearly disclose that this compares adapter
  strategies as well as services; predicate probabilities are not a distribution.
- Validate Zoom's text-only, multi-question request in a bounded live smoke test
  before calling the integration verified. Adopt native selection only if its
  contract is supplied and validated.
- Search-only policy chooses deterministically using a documented ordering of
  completion, survival, viable continuations, and progress, with stable tie breaks.
- Validate candidate IDs and scores. Authentication, timeout, malformed responses,
  and missing answers must produce explicit failures, never heuristic fallback.
- Use bounded request timeouts, explicit call limits, and no automatic retries by
  default. Existing `TYPESAFE_API_KEY` and `ZOOM_API_KEY` configuration remains valid.

### FR-03 — Separate model decisions from assistance

- Disable automatic escape search and automatic follow-up execution in the first
  version. Models may select a documented composite macro as one candidate.
- If escape/follow-up assistance is introduced later, expose it as a named setting
  shared by all policies. Log its trigger, action sequence, and source separately
  from provider-selected actions; report assisted and unassisted counts.
- Never rewrite a failed model decision after seeing its actual outcome.

### FR-04 — Two evaluation tracks

1. **Identical-state comparison:** build a versioned corpus of emulator checkpoints
   spanning open ground, enemies, obstacles, gaps, and landing situations. Freeze
   the state and candidate outcomes before evaluation. Ask all policies to rank
   the same candidates. Report agreement, selection of known-fatal options when
   a surviving alternative exists, progress under the fixed horizon, errors, and
   latency. These are finite-horizon diagnostics, not proof of optimal gameplay.
2. **Episode comparison:** start each policy on the same level and seed schedule
   with equal budgets. Let trajectories diverge naturally. Run at least three
   attempts per policy for a smoke benchmark; report sample counts and individual
   results, without treating three attempts as statistical evidence of superiority.

Separate simulated-game-frame, lookahead-work, decision-count, and wall-time caps.
Stop and identify completion, death, stall, budget exhaustion, cancellation, and
provider failure independently. Define a stall as no new best progress within a
configured number of actual game frames.

### FR-05 — Comparison view and report

- Preserve the two prominent Jev/Zoom game panels. Show the search-only baseline in
  the run report; it need not occupy a third gameplay panel.
- Distinguish simulating, waiting for API, executing, stalled, completed, died, and
  failed states. A paused emulator awaiting a response must not appear unexplained.
- Provide a local readable report, alongside machine-readable artifacts, comparing
  completion counts, death/stall/error counts, best progress, simulated survival
  time, API calls, median/p95 latency, total wall time, and simulation work.
- Show per-decision before/after state, all candidate outcomes, selected candidate,
  raw scores, executed button sequence, source of action, and terminal reason.
  Explain decisions using recorded evidence; do not invent model reasoning.
- Include usage reported by each provider. Cost is unknown unless a provider-specific
  pricing configuration and sufficient usage are available; never copy TypeSafe's
  rate to Zoom or present an unknown cost as zero.
- Support offline playback of recorded actions without API calls, verifying state
  divergence against recorded checkpoints. Playback is not fresh model evaluation.

### FR-06 — Reproducibility and durable evidence

Each run must record schema version, run ID, application commit and dirty-state
status, reference provenance, dependency/emulator versions, level, seeds, action
set version, simulator settings, budgets, adapter/prompt version, and requested
and returned model identifiers when available. Record unavailable identifiers as
unknown. A fixed seed does not guarantee deterministic remote model responses.

Write decision and error events incrementally and finalize partial summaries on
failure/cancellation. Version new artifacts so older direct-control logs remain
readable or are rejected with a clear compatibility message. Do not store keys,
request authentication headers, or provider error bodies that might expose them.

## Proposed architecture

`Checkpoint / episode state → shared simulator → canonical candidate outcomes →
Jev | Zoom | deterministic ranker → shared executor → event log → report / replay`

Separate emulator/snapshot operations, simulation, provider adapters, execution,
and reporting into modules. Do not make a provider adapter responsible for game
physics or automatic recovery. Reuse the reference's experiment design; inspect
reuse terms before copying code because the reviewed checkout has no LICENSE file.

## Migration plan

1. Complete and test the current harness's per-frame observation and jump-release
   corrections as a distinct change. Preserve existing direct-mode behavior and logs
   where compatible; document changes that affect evaluation comparability.
2. Validate snapshot/restore support on the current Python 3.13 emulator stack.
   Keep it if correct. If the reference's Python 3.12/older-emulator stack is needed,
   isolate and pin that runtime rather than silently changing all dependencies.
3. Implement simulation, deterministic ranking, and offline replay first. Establish
   reproducible fixtures and execution parity without paid requests.
4. Connect Jev and Zoom adapters to the canonical outcomes, then add bounded live
   validation using securely configured keys.
5. Add paired evaluation, readable reports, and desktop status feedback. Document
   local setup, commands, assistance settings, costs, and limitations in README.

## Acceptance criteria

- [x] A repeated snapshot rollout matches RAM, images, wrapper counters, and terminal
  state; exploring candidates in a different order does not change their outcomes.
- [x] Executing a selected candidate reproduces its simulated outcome for identical
  initial state and horizon, including grounded jumps, landings, and terminal cases.
- [x] Identical-state runs deliver matching state/outcome content and candidate IDs
  to both adapters; request-envelope differences are explicit and tested.
- [x] Search-only and fixture-backed offline runs require no keys and cannot call
  either provider. They are visibly labeled and excluded from live model results.
- [x] Adapter tests cover successful parsing, stable ties, unknown/missing/duplicate
  candidates, invalid scores, authentication errors, timeouts, and malformed JSON.
- [ ] At least one successful bounded live request from each provider is recorded
  before live integration is marked verified; missing access remains a blocker.
- [x] A bounded three-attempt World 1-1 run produces one combined report with each
  policy's outcomes, counts, latency, budgets, and available usage, including failures.
- [x] A simulated wait, an actual stall, a death, a cap, and a provider failure are
  distinguishable in both the desktop view and saved report.
- [x] Replay makes zero provider calls and detects a deliberately altered checkpoint
  or action sequence; summaries remain available after interruption.
- [x] Direct and assisted mode results remain explicitly separate. No completion
  threshold is imposed that would encourage hiding valid model failures.
- [x] Local setup and evaluation commands work as documented; secrets stay ignored.

## Dependencies and unresolved items

- Securely provisioned Jev and Zoom credentials for live validation.
- Verified Zoom multi-predicate limits and response behavior; no native choice
  contract is currently available.
- Emulator snapshot compatibility and measured search cost on the supported runtime.
- Verified provider pricing if monetary comparisons are requested.
- Upstream permission/license clarification only if implementation code is copied.

## Implementation notes

Implemented as `mario-eval assisted`, `capture`, `evaluate`, and `replay` while
retaining the original direct-control command. The simulator is original code on
the existing Python 3.13 stack. Initial macros use a 48-frame horizon, bounded
landing/settling, and optionally all seven single-step continuations (`all-seven-v1`). No automatic
escape or follow-up execution is implemented.

Offline fixtures and the search-only baseline passed a bounded three-attempt
World 1-1 smoke run. This is not a measured live comparison. Both configured
services returned HTTP 403 during the one-request-per-service live smoke test;
provider access must succeed before live integration can be called verified.
Corpus coverage depends on the captured trajectory and is explicitly reported;
a short capture does not imply coverage of every required scene.
