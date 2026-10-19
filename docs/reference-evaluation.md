# Evaluation of 4esv/jev-mario

Reviewed source: https://github.com/4esv/jev-mario
Commit: `8459bbb476c73463d9d3389639c158ecca4e21b4`.

## Recommendation

Use it as the methodological reference for an additional **assisted outcome-ranking**
benchmark. Keep direct control as a separate mode. Do not replace the current
harness wholesale or describe its branching results as unassisted gameplay.

The repository is a stronger evaluation reference than the original single-agent
controller: it separates direct control, simulated latency, and lookahead; supplies
non-model controls; records unsuccessful results; and compares several models.
Its successful branch mode also removes much of the fine motor timing burden from
the service, allowing a longer and more interpretable decision comparison.

## Evidence in the repository

`runs/results.jsonl` contains 50 archived summaries. For World 1-1:

| Mode | Archived best x | Flag | Runs |
| --- | --- | --- | --- |
| Direct Jev | 686 each | No | 3 |
| Live Jev | 315 each | No | 3 |
| Branch Jev | 3161 each | Yes | 3 |
| Direct rules | 1129 | No | 1 |
| Branch search without a model | 2370 each | No | 2 |

These are archived observations, not new API measurements or an unbiased success-rate
estimate. The README explicitly says older 2-1 and 3-1 clears do not reproduce on
its latest branch implementation. None of the 50 summaries records a code commit
or seed. Selected GIFs are committed, but the corresponding detailed decision logs
are not present in the checkout.

## What the implementation actually does

- `branch.py` evaluates 11 options using save/restore. For viable options it tries
  36 two-step continuations (six choices at each step). Some docstrings still say
  16; the current code uses 36.
- Jev receives measured outcome descriptions and ranks them. It need not predict
  jump physics. The search baseline ranks by flag, survival, avoiding dead ends,
  distance, and surviving continuations.
- Macros include manually tuned, frame-exact springboard and ledge sequences.
- If all options fail its progress/survival condition, a deterministic three-move
  escape search can execute without asking Jev. A chosen option's follow-up can
  also be executed automatically. These contributions need explicit attribution.
- `live.py` makes a blocking request, then advances the previous input by the
  measured latency. It models delayed control; it is not a truly concurrent
  real-time renderer. Its rules baseline uses a fixed 0.2-second delay.
- `play.py` uses ground decisions and whole-jump execution. Some frame counters
  round up to the next decision boundary without stepping the emulator; do not
  reuse those counters as exact executed-frame measurements.

## Local verification

Installed the frozen Python 3.12 dependencies in an isolated checkout. The default
build initially failed because the interpreter expected `clang++`; selecting the
installed GCC/G++ via `CC=gcc CXX=g++` built the pinned emulator successfully.
The current project uses Python 3.13 and a newer emulator, so this is not a drop-in
dependency replacement.

Verified that a 240-frame snapshot replay matches RAM, rendered image, info, and
termination state. A complete `run right` branch-outcome simulation also restored
the starting RAM after exploring continuations. These are bounded checks, not a
proof of restoration at every level or terminal state.

Ran the unmodified direct rules baseline: **x=1129, 621 reported frames, no flag,
zero API calls**, matching the archived result. Live Jev and Zoom results have not
been reproduced because no credentials are configured in this session.

## Adaptation requirements for our comparison

1. Give Jev and Zoom exactly the same outcome descriptions, legal options, search
   budget, and macro executor. Run a third search-only baseline.
2. Evaluate both providers on saved identical decision states for ranking quality,
   then run independent end-to-end episodes for gameplay outcomes. Those answer
   different questions; do not merge their scores.
3. Keep Zoom predicate ranking clearly distinguished from Jev native Choice until
   a verified Zoom selection schema is available. The `--url` flag alone cannot
   connect Zoom: authentication, payload, and response contracts differ.
4. Log model-selected moves separately from automatic escape/follow-up moves;
   record actual frames, simulation work, wall time, API latency, raw scores,
   available usage, error/termination reasons, source commit, and model identifier.
5. Report repeated fixed-condition runs and stalls as well as flags. Avoid a single
   combined score that hides reliability, model cost, or emulator assistance.
6. Use provider-specific usage and pricing. The reference hardcodes a TypeSafe
   input-token rate and reports custom-endpoint cost as zero; neither is an
   appropriate Zoom cost estimate.
7. Add snapshot/restore, executed-action parity, API validation, and failure-log
   tests. No test suite is committed in the reference checkout. No LICENSE file
   was found; establish reuse terms before copying its implementation.

The recommendation is to adopt its experiment design and outcome-ranking approach,
with shared assistance and reproducible logs, rather than promise that changing
repositories will make either model complete Mario unaided.
