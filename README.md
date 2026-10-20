# Mario decision comparison

Two Super Mario Bros. episodes side by side: **TypeSafe Jev** and **Zoom Decisions**.
Uses [fhshaik/typesafe-mario](https://github.com/fhshaik/typesafe-mario) at commit
`ca22449ed187118d19326d1f54b01b6636578aa4` for the emulator, state parser, actions,
and, in direct mode, the unmodified Jev policy. Upstream source is installed as a dependency, not copied.

## Choose an approach

Complete [local setup](#run-locally) first. All live commands need both API keys.

| Approach | What the services receive | Zoom question | Use it to |
| --- | --- | --- | --- |
| **Assisted native choice** (default) | Current state plus measured outcomes of seven simulated moves | One `choice` among those moves | Compare Jev and Zoom on the same action-selection task during gameplay |
| **Assisted predicates** (legacy) | The same state and simulated outcomes | Seven independent “is this the best move?” predicates | Compare Zoom request formats against the older implementation |
| **Real-time assisted** | Simulated outcomes from an earlier snapshot; live game continues while planning | `choice` or `predicate` | Measure latency-sensitive gameplay without inference pauses |
| **Direct control** | Parsed current game state, without simulated future outcomes | Seven independent action predicates | Evaluate the original controllers; Jev also makes extra judgments |
| **Identical-state evaluation** | The same frozen checkpoints and simulated outcomes for every policy | `choice` or `predicate` | Compare decisions without confounding them with different gameplay trajectories |
| **Offline fixtures / search** | Game state or simulated outcomes, depending on mode | No API calls | Validate the harness, capture states, and establish a deterministic baseline |

Direct and assisted episodes run independent lanes in parallel.
Use `realtime` for continuous gameplay while decisions are pending; see below. Each emulator
pauses during its own inference; the other lane can keep playing. Identical-state
`evaluate` is a headless, case-by-case ranking workflow, not parallel gameplay.
Neither parallel scheduling nor assistance guarantees a level clear. Keep direct,
assisted, and offline results separate.

### Run each gameplay approach

**Assisted native choice — recommended starting point:**

```sh
uv run --frozen --env-file .env mario-eval assisted --zoom-question choice --episodes 1 --max-decisions 100 --wall-seconds 600
```

**Assisted independent predicates — same budgets, older Zoom format:**

```sh
uv run --frozen --env-file .env mario-eval assisted --zoom-question predicate --episodes 1 --max-decisions 100 --wall-seconds 600
```

**Original direct control — no lookahead:**

```sh
uv run --frozen --env-file .env mario-eval --max-decisions 250
```

`--zoom-question` applies to `assisted`, `realtime`, and `evaluate`; it does not change the
direct controller. Add `--headless` to any of these commands to omit the window.
Every invocation creates a separate artifact directory, so keep both directories
when comparing formats. The two assisted commands keep Jev's task unchanged.

### Continuous live playback (real-time mode)

```sh
uv run --frozen --env-file .env mario-eval realtime --zoom-question choice --episodes 1 --max-decisions 100 --wall-seconds 600 --depth 0
```

This mode keeps each emulator running while a separate emulator simulates options
and its provider decides. Desktop rendering and live game steps target 60 FPS.
Mario begins with neutral controls until the first reply; then the last selected
move continues until a new reply arrives. Jump holds release after 8/32 frames,
so waiting for the next reply does not continually retrigger jumps.

`--depth 0` reduces planning latency by omitting follow-up lookahead. Use `--depth 1`
for all-seven continuation evidence, at higher simulation cost. Compare runs only
with matching depth and limits. Slow hardware can reduce actual FPS; no emulator
frames are skipped to catch up. `--headless` also keeps real-time pacing.

Unlike paused `assisted` mode, latency now affects survival. Predictions describe
an older snapshot, so their execution-parity guarantee does not apply to the live
game. The runner applies replies on arrival, logs `observed_frame`, `applied_frame`,
and `decision_age_frames`, and discards outstanding replies when an episode ends.
The separate `realtime` report includes median/maximum decision age, API errors,
bootstrap/held controls, and replayable action sequences. Do not combine these
results with paused assisted rankings. There are no automatic escape overrides.
The decision cap ends after the last selected move has run for at least one horizon;
frame, stall, terminal, and wall-time limits may stop it sooner.

For a no-key desktop check:

```sh
uv run --frozen mario-eval realtime --offline --episodes 1 --max-decisions 2 --depth 0
```

### Give Zoom a better chance of surviving

Use **paused assisted mode, native choice, depth 1, and the optional survival guard**:

```sh
uv run --frozen --env-file .env mario-eval assisted --zoom-question choice --depth 1 --survival-guard --episodes 5 --max-decisions 100 --wall-seconds 600 --simulation-frames 400000 --headless
```

Remove `--headless` for the side-by-side window. Let all five attempts finish;
Q/Escape cancels the remaining attempts. If using the pip/venv setup below,
activate the environment, export the two API keys, and replace
`uv run --frozen --env-file .env mario-eval` with `mario-eval`.

The guard applies the **same rule to Jev, Zoom, and search**. It replaces a choice
only when it predicts death, or all seven tested follow-ups predict death, and
an evaluated surviving alternative exists. Among eligible alternatives it prefers
a completion, then the provider's highest score. It does not infer fatality from
unknown or partial evidence, retry API failures, or execute follow-ups automatically.
Waiting and retreating remain valid choices. It does not prevent all stalls or
guarantee completion.

`ranking` events retain the original provider choice and probabilities.
`survival_guard` events record the proposed/applied moves, eligible alternatives,
and reason; `execution.source` identifies replacements. The display, config,
summary, and report label guarded runs. These results measure **provider plus guard**;
omit `--survival-guard` for raw model comparisons and keep the result sets separate.
The flag is supported only by `assisted`, because real-time predictions are stale.

The regression suite reproduces four failure states from the uploaded runs and
checks that replacements and a subsequent continuation survive. This is local
survival evidence, not a measured improvement in the live service's win rate.
See [the nine-run analysis](docs/zoom-survival-review.md).

### Available Zoom request types

| API type | Response meaning | Use in this project |
| --- | --- | --- |
| `choice` | Explicit selected value plus probabilities over the listed choices | Default assisted/evaluate action selection; honors the returned choice |
| `predicate` | An independent probability for each named yes/no question | Legacy assisted/evaluate option and the direct controller |
| `score` | A fractional score over ordered levels, plus level probabilities | Documented only; no gameplay option implemented |
| Mixed questions | Named, typed answers for choice, predicate, and score in one call | Documented only; no mixed-question gameplay option implemented |

Score examples use zero-based level indices, with the score matching their
probability-weighted mean. Predicate probabilities are not a categorical
distribution. Neither provider's scores should be treated as calibrated against
the other's. See [request and response examples](docs/zoom-api.md).

## Assisted comparison (new)

The new `assisted` mode follows the experiment design of
[4esv/jev-mario](https://github.com/4esv/jev-mario): simulate possible moves, then
ask the services to rank measured outcomes. The implementation is original and
uses our existing Python 3.13 emulator stack. It includes a deterministic
search-only baseline and no automatically executed follow-ups. An optional shared
survival guard can replace predicted fatal selections; it is off by default.
The original commands below still run **direct control**, a separate benchmark.

After [local setup and `.env` configuration](#run-locally), run the live assisted
comparison with this command (works in macOS/Linux shells and Windows PowerShell):

```sh
uv run --frozen --env-file .env mario-eval assisted --episodes 1 --max-decisions 100 --wall-seconds 600
```

This loads `TYPESAFE_API_KEY` and `ZOOM_ACCESS_TOKEN` from `.env` and runs Jev, standard Zoom Decisions,
and the search baseline independently in parallel. Jev and Zoom appear side by
side; the baseline is included in the report. Add `--headless` to run without a
window. These limits allow a longer attempt but do not guarantee a level clear;
the other budgets below still apply. **Include `assisted`: omitting it starts
the original direct-control mode.**

For a short offline run without API keys:

```sh
uv run --frozen mario-eval assisted --offline --episodes 1 --max-decisions 3
```

Both displayed policies are explicitly labeled **OFFLINE FIXTURE** and use the
same deterministic ranker; they are not simulated model responses. The third,
search-only baseline appears in the report. The window distinguishes simulation,
API wait, execution, stall, death, and budget limits. Q/Escape stops the run;
an in-flight request worker is terminated on cancellation.

Validate live access with one call per service before spending more:

```sh
uv run --frozen --env-file .env mario-eval assisted --headless \
  --episodes 1 --max-decisions 1 --timeout 15
```

Then run a bounded three-attempt comparison:

```sh
uv run --frozen --env-file .env mario-eval assisted --episodes 3 --max-decisions 25
```

For Windows PowerShell, put each multi-line example on **one line** (the `\`
continuation above is for macOS/Linux shells).

Every attempt uses matching level and seed across Jev, Zoom, and search. Episodes
are independent, so states diverge after different choices. Lookahead supplies
assistance: completion is not evidence of unaided gameplay. Each lane independently
simulates outcomes, requests a decision, and executes
its move. Jev, Zoom, and the search baseline run concurrently; no lane waits for
another lane’s response or move. Each emulator pauses only during its own
simulation and API calls. API latency excludes simulation; per-lane wall time
includes its own simulation, requests, execution, and CPU contention. Faster
responses can produce faster wall-clock progress, without advancing game time
while that lane is waiting. Desktop rendering and move playback target 60 FPS,
with processing time included in each frame interval. Slow machines can achieve
less; emulator frames are never skipped to catch up. Simulation/API pauses are
intentional, so this is smooth playback between decisions, not uninterrupted
real-time gameplay. Headless runs do not throttle emulator playback.
The three-attempt smoke benchmark
is not a statistically conclusive performance study.

### Zoom question format

Assisted mode and identical-state evaluation now use Zoom's native `choice`
question by default, matching Jev's action-selection task. The response's explicit
choice is honored and its categorical probabilities are logged. To compare against
the old independent-predicate setup, add `--zoom-question predicate` to either
command. The setting is recorded in config.json. Direct control still uses predicates.
See [Zoom formats](docs/zoom-api.md) for the released API reference and earlier
choice, predicate, score, and mixed-question examples.

### Choose the Zoom model to compare against Jev

For `assisted`, `realtime`, and `evaluate`, use `--zoom-model`. Jev keeps its
`jev-latest` default; leave `--model` unset. Both services use native choice by default.

| Comparison | Flag |
| --- | --- |
| Jev vs standard Decisions | `--zoom-model zoom-decisions` (default) |
| Jev vs Decisions Pro | `--zoom-model zoom-decisions-pro` |

Choose one Zoom model per run. `--zoom-question` selects the question format,
not the model. These flags do not apply to the original direct-control command.

In your local `.env`, set `TYPESAFE_API_KEY` and `ZOOM_ACCESS_TOKEN`. The documented
Zoom API requires a bearer access token with `aiservices:write:decide:admin` and a
Zoom AI Services or Universal SDK entitlement. Pro may need an additional entitlement.
Never commit tokens. Obtain/refresh the access token through your Zoom OAuth setup;
this runner does not refresh expired tokens. If `ZOOM_ACCESS_TOKEN` is absent, the
runner retains the earlier `ZOOM_API_KEY` / `x-api-key` path for legacy deployments;
that path is not the authentication documented in the released reference.

```sh
# Standard Decisions versus Jev
uv run --frozen --env-file .env mario-eval assisted --zoom-model zoom-decisions --episodes 5 --max-decisions 100 --wall-seconds 600 --simulation-frames 400000 --survival-guard

# Decisions Pro versus Jev, with the same settings
uv run --frozen --env-file .env mario-eval assisted --zoom-model zoom-decisions-pro --episodes 5 --max-decisions 100 --wall-seconds 600 --simulation-frames 400000 --survival-guard
```

If using an activated Python virtual environment without uv, load the variables
into your shell and replace `uv run --frozen --env-file .env mario-eval` with
`mario-eval`. The CLI itself does not load `.env`.

Each command runs Jev, the selected Zoom model, and the search baseline. These are
assisted runs; guard interventions are logged. To measure unguarded model choices,
omit `--survival-guard` in **both** commands. For identical input states, first capture
one corpus, then use that same path in both evaluations:

```sh
uv run --frozen mario-eval capture --max-decisions 12 --headless
uv run --frozen --env-file .env mario-eval evaluate artifacts/<capture-run-id>/corpus.json --zoom-model zoom-decisions --max-decisions 12 --wall-seconds 600
uv run --frozen --env-file .env mario-eval evaluate artifacts/<capture-run-id>/corpus.json --zoom-model zoom-decisions-pro --max-decisions 12 --wall-seconds 600
```

The requested Zoom model is saved in `config.json` and each request; returned model,
usage and latency are in the ranking logs. A missing/different returned model causes
`model_mismatch`, never silent fallback. Model IDs are public aliases, not immutable
weight versions. Real-time comparisons also measure latency's effect on gameplay.

### Matching provider parameters

Native choice (`--zoom-question choice`, the default) uses one shared objective,
canonical evidence, ordered action set, and per-action descriptions for both
services. Each episode gets the same level/seed, simulation configuration, stop
limits, timeout cap, and survival-guard rule. Independent gameplay states diverge
after different moves; use `capture` + `evaluate` below to compare identical states.
Real-time mode also permits different decision ages because service latency differs.

`config.json.comparison_parameters` explicitly records what is and is not matched:

| Control | Jev | Zoom |
| --- | --- | --- |
| Default question | Native choice | Native choice |
| Objective and action descriptions | Shared | Shared |
| Model selection | `--model` (default `jev-latest`) | `--zoom-model` (default `zoom-decisions`; alternative `zoom-decisions-pro`) |
| Temperature, top-p, inference seed, output limit | Not sent; effective defaults unknown | Not sent; effective defaults unknown |

**Equal internal model settings cannot be verified from these API contracts.**
The emulator's `--seed` is not an inference seed. We do not invent unsupported
Zoom parameters or claim omitted defaults are identical. The model identifier
returned by each service is recorded in ranking metadata. `--model` applies only
to Jev. Legacy Zoom predicates are explicitly marked as nonmatching question
formats in the configuration; use native choice for a matched task.

Successful live ranking events include `request_contract_sha256`. For the same
checkpoint, matching hashes confirm equal submitted state, question, instructions,
ordered choices/descriptions, and other explicit request parameters after normalizing
the provider envelopes. Model identity is deliberately excluded. This does not
verify hidden defaults, tokenization, or model weights. Fingerprints can differ
across independent episodes because the inputs differ. These audit fields do not
change the v5 prompt or gameplay policy.

### Budgets and assistance

Seven versioned macros use a 48-frame horizon, up to 72 extra landing frames,
and four neutral settling frames. `--depth 1` (default) evaluates all seven single-move
continuations per surviving **or nonterminal airborne/unknown** candidate, including
walk, hop, wait, and back. This is recorded as
`continuation_set: all-seven-airborne-v2`. It closes the previous blind spot where
an airborne endpoint had no tested next moves, at additional simulation cost.
Truncated or terminated emulators are never expanded. Only the selected candidate is executed;
continuations provide evidence, not automatic actions. `--depth 0` is faster but
changes the experiment. Airborne or truncated outcomes are recorded as unknown,
not silently classified as fatal or safe.

Defaults per policy/episode: `--max-decisions 25`, `--game-frames 3600`,
`--simulation-frames 200000`, `--wall-seconds 180`, `--stall-frames 360`, and
`--timeout 30`. Simulation frames and actual game frames have separate caps.
A stall means no new best position within the configured actual frame interval.
Simulation can take much longer than the resulting gameplay; its status is visible.

### Targeted progress and deeper-lookahead experiment

The v6 prompt and `progress-cycles-v2` evidence separate immediate displacement,
immediate endpoint gain, and immediate completion from hypothetical follow-up
progress. A zero-progress move does not earn actual progress merely because a later
jump could advance. Survival still takes priority, and waits/retreats remain valid.

`--depth 1` remains the default (candidate plus one follow-up). Optional `--depth 2`
tests two follow-ups, up to three moves in total. Compact `third_move_summary` fields
report surviving/fatal/unknown paths, completions, best total displacement, and
follow-up sequences. Terminal paths stop early. Counts are not probabilities;
unknown outcomes are not treated as safe or fatal. Exploration restores the original
state and history. No follow-up executes automatically, and the survival guard still
uses its original one-follow-up rule.

The extra horizon exposed a trap at x=1823 in the targeted Pro recording: `walk`
has no surviving three-move route, while `wait` has seven. This is simulator evidence,
not a measured model improvement or guarantee of eventual completion.

Compare updated evidence at depth 1 against depth 2 on the **same starting
checkpoints**, with both providers receiving the same depth. For `evaluate`, depth
comes from the saved corpus; passing `--depth 2` does not change an existing corpus.
For new captures or gameplay, explicitly use `--depth 2`, for example:

```sh
uv run --frozen mario-eval capture --depth 2 --max-decisions 12 --headless --simulation-frames 1000000 --wall-seconds 1200
uv run --frozen --env-file .env mario-eval assisted --zoom-model zoom-decisions-pro --depth 2 --episodes 10 --max-decisions 100 --simulation-frames 1000000 --wall-seconds 1200 --headless
```

Use identical budgets for standard Decisions, Pro, and their Jev comparisons. Extra
lookahead costs more simulation and can increase API input size; report those costs.
Keep the earlier v5 results unchanged. Old corpora are rejected by v2 evaluation;
recapture or explicitly reconstruct their prefixes into new versioned corpora.
Targeted failure cases are development data, not held-out evidence of generalization.
See [the investigation and validation plan](docs/targeted-investigation.md).

### Shared history and continuation evidence

Both providers receive the same `outcome-ranker-v6` instructions and fields:

- `history.recent_controls`: the last eight groups of actual controller buttons,
  with their frame counts and displacement. These are executed controls, not
  hypothetical rollouts or a record of the model's reasoning.
- `history.recent_decisions`: the last 12 actually applied macros, including start/end
  states and completion. Hypothetical branches never enter this history. This is
  available for paused assisted runs; real-time runs leave it empty.
- `history.current_area_previous_visits`: prior decisions within four pixels in x/y,
  with matching grounded/power status. This is approximate position history, not
  proof of an identical emulator state.
- `history.frames_since_best_x`: actual frames without a new farthest position.
  Retreats and useful waiting can increase this counter too.
- Each outcome's `continuation_summary`: tested/available counts, surviving move
  names, fatal/unknown counts, coverage, and earliest fatal follow-up frame.
- Each outcome's `progress_summary`: best total displacement across the candidate
  and a surviving follow-up, the corresponding follow-up names, endpoint x, gain
  beyond the episode's best x, and previous same-move attempts in this area that
  gained no new ground. Unknown/dead follow-ups do not count as surviving. Missing
  surviving follow-ups produce null progress, not a claim of zero or inevitable death.

Complete coverage means every available move was tested for one bounded follow-up,
not that long-term safety is known. Depth zero and unexpanded outcomes are explicitly
untested. The history is reconstructed from recorded controls and restored after
lookahead, so hypothetical actions never pollute the next request.

By default, neither provider is overridden. Instructions prioritize survival before
distance and explicitly allow waiting or retreating. Zoom choice descriptions now
contain the same per-candidate evidence as Jev criteria, binding each label to its
measured outcome. These are prompt/evidence changes, not model fine-tuning.
The [optional guard](#give-zoom-a-better-chance-of-surviving) adds execution assistance
to every lane.

### Avoid safe but unproductive cycles

The shared v5 objective compares surviving two-move progress before immediate
movement. In the uploaded stalled Zoom attempt, a `jump` advanced 48 pixels but
left only waiting or retreating as surviving continuations. A `hop` advanced 16,
then a surviving `jump` advanced another 63: **79 pixels over two moves**.
The summary exposes this distinction without adding more lookahead depth.

Recent decision history helps recognize retreat/reapproach loops and repeated
walks with zero movement. It is a hint, not an action ban: waiting or retreating
can be necessary, and similar positions can have different enemies and timing.
The survival guard still intervenes only for predicted fatal choices. No automatic
loop escape or progress override is added. Both providers receive the same fields
and instructions; no level coordinates or winning action sequence are hard-coded.

Run the same five-attempt command above after pulling this change. Inspect
`repeated_area_choice`, `missed_surviving_progress`, and the chosen outcome's
`progress_summary`. A full-stage improvement from v5 still needs live measurement.

### Read the report

The terminal immediately prints a unique `artifacts/<run-id>/` directory:

| File | Purpose |
| --- | --- |
| `report.md` | Readable aggregate and per-attempt comparison; open in your editor |
| `summary.json` | Machine-readable outcomes, progress, frames, latency, budgets, and failures |
| `config.json` | Code/dependency versions, dirty-tree status, model request, seeds, simulation settings |
| `<policy>-<attempt>.jsonl` | Canonical evidence, request bodies without headers, raw scores, actual controls, before/after fingerprints, errors |

Logs flush incrementally and reports retain partial episodes on cancellation or
provider failure. Provider usage is preserved when returned. Cost stays **unknown**
until a provider-specific pricing calculation is implemented. Neither native-choice
scores nor legacy independent-predicate scores are calibrated across providers.
Legacy predicate scores must not be treated as a categorical distribution.
Offline fixtures are never included as live model measurements.

The **Decision diagnostics** table and each ranking event distinguish immediate
predicted death, all tested follow-ups fatal, unknown outcomes, incomplete follow-up coverage,
non-forward selections, and repeated no progress. The last metric counts selecting
nonpositive displacement after at least one horizon without a new best position;
it can flag deliberate retreats. Unknown outcomes count as incomplete when their
follow-ups are untested. Guard overrides are counted separately; selection diagnostics
always describe the original provider choice. These are diagnostics, not model accuracy or
proof that an episode must fail. In identical-state reports, checkpoint x is the
input position, not progress achieved by a provider.

### Compare decisions on identical states

**Recapture corpora without `evidence_version: progress-cycles-v2`.** The new
evidence includes decision history and two-move progress. Evaluation reconstructs
retained macro boundaries and outcomes from prefix controls, and rejects stale or
altered history. Old episode logs still support replay; they do not silently acquire
new model evidence. The simulation still supports the original v1 expansion rules.

Capture a bounded search trajectory without keys, then evaluate the frozen
checkpoints with both services and the deterministic baseline:

```sh
uv run --frozen mario-eval capture --episodes 1 --max-decisions 12 --headless
uv run --frozen --env-file .env mario-eval evaluate artifacts/<capture-run-id>/corpus.json --max-decisions 12
```

Replace `<capture-run-id>` with the printed directory. Add `--offline` to the
`evaluate` command for a zero-API fixture check. The corpus records replayable
action prefixes and geometry tags, includes an airborne sample when encountered,
and lists missing scene coverage. A short trajectory is not a balanced benchmark;
inspect `coverage` and `missing_coverage` before drawing conclusions.

For a controlled choice-versus-predicate comparison, use the **same corpus file**
and identical limits in both commands (replace the placeholder path):

```sh
uv run --frozen --env-file .env mario-eval evaluate artifacts/<capture-run-id>/corpus.json --zoom-question choice --max-decisions 3 --wall-seconds 600
uv run --frozen --env-file .env mario-eval evaluate artifacts/<capture-run-id>/corpus.json --zoom-question predicate --max-decisions 3 --wall-seconds 600
```

Each command calls both providers on up to three cases, plus the zero-API search
baseline. Jev is called again in the second run; its responses can vary. Compare
Zoom's selected moves, simulated survival/continuations, progress, and latency
across the two directories. Confirm matching `corpus_sha256` and simulation
settings in config.json. The existing captured corpus follows search's trajectory;
it does not automatically include failure states from uploaded provider logs.

Evaluation first replays and re-simulates each checkpoint, rejecting changed
fingerprints or outcomes before scoring that case. Results include `rankings.jsonl`,
`agreement.json`, known-fatal selections when a survivor existed, and per-case
chosen progress. These are finite-horizon diagnostics, not an optimality claim.
A failed case revalidation stops evaluation; already written results remain.
Evaluation wall-time and simulation budgets span the entire evaluation, including
checkpoint reconstruction. `--game-frames` caps each action prefix, and
`--max-decisions` caps cases and therefore calls per provider. The exact corpus
and its SHA-256 hash are saved with the evaluation. Each request has a total
deadline enforced by a separate worker process; latency includes worker startup.

### Verify replay without API calls

```sh
uv run --frozen mario-eval replay artifacts/<run-id>/jev-001.jsonl
```

Use `fixture-jev-001.jsonl` for an offline run. Replay re-executes the actual recorded
buttons and verifies state fingerprints, including partial executions and the end
state. This is headless verification, not video playback or fresh inference.
It requires matching dependency versions and assisted artifact schemas. Old
direct-control logs are rejected with an explicit message. Checkpoints store
JSON action prefixes rather than opaque executable serialization or ROM data.

A cloud screenshot can be captured using SDL's dummy display:

```sh
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run --frozen mario-eval assisted \
  --offline --episodes 1 --max-decisions 1 --depth 0 --exit-when-done \
  --screenshot artifacts/assisted-comparison.png
```

See [FR-001](docs/feature-requests/FR-001-assisted-mario-comparison.md) and the
[reference evaluation](docs/reference-evaluation.md) for scope and rationale.

## Run locally

### 1. Install prerequisites and clone

Install [Git](https://git-scm.com/downloads) and
[uv](https://docs.astral.sh/uv/getting-started/installation/) for your operating
system. Run these commands in Terminal (macOS/Linux) or PowerShell (Windows):

```sh
git clone https://github.com/jenzushsu/super-mario-eval.git
cd super-mario-eval
uv python install 3.13
uv sync --frozen --extra dev --python 3.13
```

Run all remaining commands from the `super-mario-eval` directory. `uv` creates
and uses `.venv` automatically; you do not need to activate it. The graphical
comparison requires a local desktop display. On a server or a machine without
one, use `--headless`.

### 2. Check the game without API keys

```sh
uv run --frozen mario-eval --offline --max-decisions 10
```

This opens two game panels and uses **two heuristic controllers**, visibly labeled
OFFLINE. No API keys or paid model calls are needed. This verifies the local game
and display, not Jev or Zoom performance. Press **Q** or **Escape**, or close the
window, to exit. The window stays open when the decision limit is reached.

### 3. Configure the TypeSafe and Zoom secrets

You need your own credentials; the repository does not contain secrets:

| Variable | Credential required | Used for |
| --- | --- | --- |
| `TYPESAFE_API_KEY` | A TypeSafe API key with access to Jev/System One, obtained through your TypeSafe account or administrator | Requests to `api.typesafe.ai` through the TypeSafe SDK |
| `ZOOM_ACCESS_TOKEN` | Zoom bearer access token with `aiservices:write:decide:admin` and AI Services or Universal SDK entitlement; Pro may need additional entitlement | `Authorization: Bearer ...` for assisted, realtime, and evaluate |
| `ZOOM_API_KEY` | Optional legacy Decisions API key from the earlier sample access program | `x-api-key` fallback when no access token is set; required by the original direct controller |

Use an **access token**, not an OAuth client secret or meeting SDK credential.
Obtain and refresh it through your Zoom OAuth setup; the runner does not refresh
expired tokens. `ZOOM_ACCESS_TOKEN` takes precedence over `ZOOM_API_KEY` in the
new comparison modes. The released reference documents bearer authentication;
legacy API-key support is retained for existing users, not guaranteed for new accounts.
See the [Zoom API reference](https://developers.zoom.us/docs/api/ai-services.md).

Copy the template:

**macOS / Linux**

```sh
cp .env.example .env
```

**Windows PowerShell**

```powershell
Copy-Item .env.example .env
```

Open `.env` in your local editor. Uncomment/add `ZOOM_ACCESS_TOKEN`, replace
the placeholders, and remove the unused legacy key line. Keep these names:

```dotenv
TYPESAFE_API_KEY="replace_with_your_typesafe_key"
ZOOM_ACCESS_TOKEN="replace_with_your_zoom_access_token"
```

`.env` is gitignored. Keep real keys out of `.env.example`, source files, commits,
logs, screenshots, and chat. Cloud environment secrets are not automatically
available on your local machine.

The Python app does **not** load `.env` itself. The `--env-file .env` option on
`uv run` loads it into the app's process. If you already exported these variables
in your terminal, those values take precedence over `.env`; clear or update stale
values before testing.

### 4. Validate one live decision

```sh
uv run --frozen --env-file .env mario-eval assisted --zoom-model zoom-decisions --headless --max-decisions 1 --wall-seconds 120
```

This makes one live decision request per provider and includes the zero-API search
baseline. It may incur usage charges. Check `summary.json` for provider errors and
`zoom-001.jsonl` for the returned model. Repeat with
`--zoom-model zoom-decisions-pro` to validate Pro access. A successful standard
request does not establish Pro entitlement; API failures are not gameplay losses.

### 5. Open the live side-by-side comparison

For the **assisted comparison**, run:

```sh
uv run --frozen --env-file .env mario-eval assisted --episodes 1 --max-decisions 100 --wall-seconds 600
```

Add `--zoom-model zoom-decisions-pro` for Pro, or leave it unset for standard
Decisions. See [model comparison commands](#choose-the-zoom-model-to-compare-against-jev)
for matched five-run and identical-state evaluations.

For the original **direct-control comparison** (legacy `ZOOM_API_KEY` required;
no Zoom model selector or bearer-token support), run:

```sh
uv run --frozen --env-file .env mario-eval --max-decisions 250
```

Jev runs on the left and Zoom Decisions on the right. Both start on the same
level and seed. Press **Q** or **Escape** to exit; an in-flight API call may need
to finish or time out before the process exits. The window remains open after
the episodes finish. Add `--exit-when-done` to close it automatically.

For a run without a window:

```sh
uv run --frozen --env-file .env mario-eval --headless --max-decisions 250
```

Each run writes separate logs and a summary under `artifacts/`. API failures
produce a nonzero exit and an error in the affected provider's summary/log;
check those files before treating a run as successful.

### Troubleshooting

- **Missing key:** run with `uv run --frozen --env-file .env ...`, from the project
  directory, and check the exact variable names and that placeholders are replaced.
- **HTTP 401/403:** verify token expiry, the `aiservices:write:decide:admin` scope,
  and the required Zoom entitlement. Pro may require separate access. Check whether
  a stale exported `ZOOM_ACCESS_TOKEN` is overriding your intended credentials.
- **`model_mismatch`:** the response omitted the model or returned a different
  variant. Check the requested model and account access; the runner never silently
  falls back from Pro to standard Decisions.
- **Connection error:** allow outbound HTTPS to `api.typesafe.ai` and `api.zoom.us`
  through your firewall or proxy. Keep TLS verification enabled.
- **Zoom response validation error:** inspect the safe diagnostic in the run
  summary and the saved `zoom_question` setting for assisted runs. The adapter
  expects the selected choice or predicate response described in
  [docs/zoom-api.md](docs/zoom-api.md); direct control expects predicates.
  Additional API compatibility work may be needed if the service differs. Do not treat this as a model score.
- **No display / video device:** run from a desktop session or add `--headless`.
  To capture an offline frame on a headless macOS/Linux environment:

  ```sh
  SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run --frozen mario-eval \
    --offline --max-decisions 10 --exit-when-done --screenshot artifacts/comparison.png
  ```

## Direct-control comparison methodology

- Same level, seed (123), seven legal actions, parser, and eight emulator frames per action.
- Two independent episodes; states diverge after the models choose different actions.
- Each lane requests decisions and executes moves independently in parallel. Its
  emulator pauses during its own inference; the other lane can keep playing.
  Latency affects wall-clock progress but does not consume in-game time. This is a
  decision-quality comparison, not the upstream real-time latency-sensitive mode.
- Jev retains its native Choice, Noul and Score request. Zoom asks seven independent
  predicates, one per candidate action, and selects the highest probability.
  Ties use the shared action order. Predicate scores are **not normalized** and
  must not be interpreted as a categorical distribution or compared directly
  with Jev confidence. Jev's extra judgments also affect latency comparability.
- Zoom receives text JSON, no screenshots, matching Jev's information source.
  User-supplied logs demonstrate successful text-only multi-predicate calls.
  Assisted mode additionally supports native choice; see docs/zoom-api.md.
- This evaluates the two controller implementations, including their prompts and
  question types, not an isolated causal comparison of the underlying models.

Each run creates a unique `artifacts/` directory with `config.json`, `jev.jsonl`,
`zoom.jsonl`, and `summary.json`. Logs include observations, decisions, reward,
progress, latency, and Zoom request/usage metadata when available. Failed provider
calls stop that lane and cause a nonzero exit; no heuristic fallback masks failures.
There are no automatic retries or background paid requests. Default limit: 250
calls per provider. Start with `--max-decisions 1` when validating credentials.

Live runs need network access to `api.typesafe.ai` and `api.zoom.us` and both keys.
Do not commit credentials, ROMs, or generated artifacts. No game data is bundled
in this repository; the emulator dependency supplies its runtime assets.

## Tests

```sh
uv run --frozen --extra dev pytest -q
uv run --frozen --extra dev ruff check src tests
uv run --frozen --extra dev ruff format --check src tests
```

API schema reference and remaining live validation: [docs/zoom-api.md](docs/zoom-api.md).
