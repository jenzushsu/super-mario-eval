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
| **Direct control** | Parsed current game state, without simulated future outcomes | Seven independent action predicates | Evaluate the original controllers; Jev also makes extra judgments |
| **Identical-state evaluation** | The same frozen checkpoints and simulated outcomes for every policy | `choice` or `predicate` | Compare decisions without confounding them with different gameplay trajectories |
| **Offline fixtures / search** | Game state or simulated outcomes, depending on mode | No API calls | Validate the harness, capture states, and establish a deterministic baseline |

Direct and assisted episodes run independent lanes in parallel. Each emulator
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

`--zoom-question` applies only to `assisted` and `evaluate`; it does not change the
direct controller. Add `--headless` to any of these commands to omit the window.
Every invocation creates a separate artifact directory, so keep both directories
when comparing formats. The two assisted commands keep Jev's task unchanged.

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
search-only baseline, no automatic escape moves, and no unselected follow-ups.
The original commands below still run **direct control**, a separate benchmark.

After [local setup and `.env` configuration](#run-locally), run the live assisted
comparison with this command (works in macOS/Linux shells and Windows PowerShell):

```sh
uv run --frozen --env-file .env mario-eval assisted --episodes 1 --max-decisions 100 --wall-seconds 600
```

This loads `TYPESAFE_API_KEY` and `ZOOM_API_KEY` from `.env` and runs Jev, Zoom,
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
while that lane is waiting. The three-attempt smoke benchmark
is not a statistically conclusive performance study.

### Zoom question format

Assisted mode and identical-state evaluation now use Zoom's native `choice`
question by default, matching Jev's action-selection task. The response's explicit
choice is honored and its categorical probabilities are logged. To compare against
the old independent-predicate setup, add `--zoom-question predicate` to either
command. The setting is recorded in config.json. Direct control still uses predicates.
See [Zoom formats](docs/zoom-api.md) for the supplied choice, predicate, score,
and mixed-question contracts. Native choice gameplay improvement is not yet verified.

### Budgets and assistance

Seven versioned macros use a 48-frame horizon, up to 72 extra landing frames,
and four neutral settling frames. `--depth 1` (default) evaluates three single-move
continuations per surviving candidate. Only the selected candidate is executed;
continuations provide evidence, not automatic actions. `--depth 0` is faster but
changes the experiment. Airborne or truncated outcomes are recorded as unknown,
not silently classified as fatal or safe.

Defaults per policy/episode: `--max-decisions 25`, `--game-frames 3600`,
`--simulation-frames 200000`, `--wall-seconds 180`, `--stall-frames 360`, and
`--timeout 30`. Simulation frames and actual game frames have separate caps.
A stall means no new best position within the configured actual frame interval.
Simulation can take much longer than the resulting gameplay; its status is visible.

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

### Compare decisions on identical states

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

You need your own keys; the repository does not contain credentials:

| Variable | Credential required | Used for |
| --- | --- | --- |
| `TYPESAFE_API_KEY` | A TypeSafe API key with access to Jev/System One, obtained through your TypeSafe account or administrator | Requests to `api.typesafe.ai` through the TypeSafe SDK |
| `ZOOM_API_KEY` | A key provisioned for Zoom AI Services **Decisions API**, obtained through your Zoom AI Services access provider or administrator | The `x-api-key` header on `https://api.zoom.us/v2/aiservices/decisions/decide` |

The supplied Zoom samples use an API key, not a Zoom meeting SDK credential or an
OAuth client secret. A regular Zoom account alone does not establish Decisions
API access. No public key-provisioning procedure was supplied with the samples;
use the access channel that provided them if you do not yet have a key.

Copy the template:

**macOS / Linux**

```sh
cp .env.example .env
```

**Windows PowerShell**

```powershell
Copy-Item .env.example .env
```

Open `.env` in your local editor and replace both placeholders with your actual
keys. Keep the variable names exactly as shown:

```dotenv
TYPESAFE_API_KEY="replace_with_your_typesafe_key"
ZOOM_API_KEY="replace_with_your_zoom_decisions_key"
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
uv run --frozen --env-file .env mario-eval --headless --max-decisions 1
```

This makes a live request to each provider and may incur usage charges. A
successful run prints summaries for both providers with `count: 1` and
`error: null`, followed by the artifact directory. The Zoom text-only,
seven-predicate request succeeded in user-supplied runs; verify access with your own key.

### 5. Open the live side-by-side comparison

For the **assisted comparison**, run:

```sh
uv run --frozen --env-file .env mario-eval assisted --episodes 1 --max-decisions 100 --wall-seconds 600
```

See [Assisted comparison](#assisted-comparison-new) for its budgets and reports.

For the original **direct-control comparison**, run:

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
- **HTTP 401/403:** verify the key and service access with the relevant provider.
  For Zoom, the key must authorize the Decisions endpoint specifically.
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
