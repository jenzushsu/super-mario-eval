# Super Mario decision comparison

Compare **Zoom Decisions**, **Zoom Decisions Pro**, and **TypeSafe Jev** as they
choose moves in Super Mario Bros. Watch Jev and a selected Zoom model side by
side, inspect their decisions, and compare them with a deterministic search baseline.

The recommended mode is **simulation-assisted gameplay**: the emulator tests seven
candidate moves, then each API receives structured game state and simulated
outcomes and selects a move. Models receive text, not game screenshots. Gameplay
pauses during simulation and inference.

Read the [Zoom Decisions API case study](docs/blog/zoom-decisions-mario/medium.md)
for the integration, results, charts, and lessons learned, or watch the
[annotated stage-clear replay](docs/blog/zoom-decisions-mario/assets/decisions-stage-1-1-replay.mp4).
The replay omits simulation and API waiting time.

## How it works

1. Each controller starts its own episode on the same level and seed.
2. The simulator measures candidate moves and their possible continuations.
3. Jev and Zoom choose through their APIs; search uses fixed rules without API calls.
4. Each controller executes its choice, and the runner records the result.

Once choices differ, gameplay states can diverge. For a comparison on exactly the
same inputs, use the [saved-checkpoint evaluation](docs/usage.md#compare-decisions-on-identical-states).
Search is a baseline, not ground truth or an optimal solver.

## Quick start

Install [Git](https://git-scm.com/downloads) and
[uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
git clone https://github.com/jenzushsu/super-mario-eval.git
cd super-mario-eval
uv python install 3.13
uv sync --frozen --python 3.13
```

Run the remaining commands from the project directory. These single-line commands
work in macOS/Linux terminals and Windows PowerShell. A local desktop is required
for the game window; add `--headless` to run without it.

### 1. Check your setup without API credentials

```sh
uv run --frozen mario-eval assisted --offline --episodes 1 --max-decisions 3
```

The displayed controllers are labeled **OFFLINE FIXTURE** and use a deterministic
ranker. This checks the game and display; it does not measure model performance.
Press **Q** or **Escape** to exit. Add `--exit-when-done` to close the window automatically.

### 2. Configure credentials

Create a `.env` file in the project directory:

```dotenv
TYPESAFE_API_KEY="your_typesafe_api_key"
ZOOM_ACCESS_TOKEN="your_zoom_access_token"
```

Live comparisons require access to both services. Use a Zoom bearer access token,
not an OAuth client secret. The integration expects the
`aiservices:write:decide:admin` scope and applicable AI Services or Universal SDK
entitlement; Pro access may require additional entitlement. See the
[authentication notes](docs/zoom-api.md) for details.

The runner does not refresh expired tokens. `.env` is ignored by Git; never commit
credentials. The `--env-file .env` option loads this file, but existing environment
variables take precedence. `ZOOM_API_KEY` is supported as a legacy fallback when
`ZOOM_ACCESS_TOKEN` is absent.

### 3. Verify one live decision

```sh
uv run --frozen --env-file .env mario-eval assisted --zoom-model zoom-decisions --episodes 1 --max-decisions 1 --wall-seconds 120 --headless
```

This makes one request per provider and may incur API charges. Open the printed
artifact directory and check `summary.json` for errors. `decision_cap` is expected
for this short check: it stops after one decision.

### 4. Run the comparison

```sh
uv run --frozen --env-file .env mario-eval assisted --zoom-model zoom-decisions --depth 1 --episodes 1 --max-decisions 100 --simulation-frames 1000000 --wall-seconds 1200
```

To compare Jev with **Decisions Pro**, replace `zoom-decisions` with
`zoom-decisions-pro`. Jev defaults to `jev-latest`. The search baseline runs
alongside both models and appears in the report.

Keep `assisted` in the command: omitting it starts the legacy direct controller,
which uses a different request format and authentication path.

## Read the results

Every run writes a separate directory under `artifacts/`:

| File | What it contains |
| --- | --- |
| `report.md` | Aggregate results and individual episode outcomes |
| `summary.json` | Completion, deaths, stalls, progress, and provider errors |
| `config.json` | Models, budgets, simulation settings, and code provenance |
| `<policy>-<attempt>.jsonl` | Submitted evidence, choices, execution, latency, and available usage metadata |

In assisted reports, **`completed` means Mario reached the stage's clear condition**.
For the default stage 1-1, this means reaching the flag—not completing the entire
game. In `summary.json`, look for `"reason": "completed"` per episode or
`"outcomes": {"completed": 10}` for ten clears. Progress and reward alone do not
establish completion.

A `provider_error` is an API failure, not a Mario death. Record it separately.
Dollar cost remains unknown until provider pricing is applied to usage; decision
counts and simulation frames are not dollar-cost estimates.

## Options and advanced workflows

| Option or workflow | Purpose |
| --- | --- |
| `--headless` | Run without a game window |
| `--episodes N` | Run multiple attempts per controller |
| `--depth 0`, `1`, or `2` | Change lookahead; depth 1 is the default, depth 2 includes three-move outcomes |
| `--survival-guard` | Allow a shared rule to replace some predicted fatal choices; off by default |
| `capture` and `evaluate` | Compare providers on the same saved checkpoints |
| `replay` | Verify logged gameplay without new API calls |
| `realtime` | Keep gameplay moving while planning and inference are pending |

The survival guard cannot guarantee completion or prevent every stall. Keep
results with it enabled separate from unguarded runs. Real-time mode also measures
a different task because inference latency affects gameplay.

See the [detailed usage guide](docs/usage.md) for budgets, model comparisons,
checkpoint evaluation, replay, legacy modes, and historical experiment notes.
Use `uv run --frozen mario-eval assisted --help` to inspect assisted options.

## Case study and limitations

In the final depth-1 case-study batches, **standard Decisions and Decisions Pro
each cleared stage 1-1 in 10 of 10 episodes**, with survival guard off. Jev also
cleared all ten episodes in each pairing. Deeper lookahead reduced Zoom's decision
counts but required substantially more simulation work.

These are repeated runs on one development stage, with simulation assistance—not
a general model ranking or a raw-vision gameplay benchmark. The recorded runs also
contain an unresolved local-source-change flag (`dirty: true`), and overlapping
batches limit timing comparisons. See the
[case study](docs/blog/zoom-decisions-mario/medium.md) and
[source notes](docs/blog/zoom-decisions-mario/README.md) for evidence and limitations.

## Troubleshooting

- **Missing credentials:** include `--env-file .env` and check the variable names.
- **HTTP 401 or 403:** check token expiry, scopes, and account entitlement. Verify Pro access separately.
- **`model_mismatch`:** inspect the requested and returned model IDs; the runner does not silently substitute standard Decisions for Pro.
- **No display:** add `--headless` or run from a desktop session.
- **Other provider errors:** inspect the saved error details before repeating a large batch.

More diagnostics are in the [troubleshooting guide](docs/usage.md#troubleshooting).

## Development and credits

Install development dependencies and run the checks:

```sh
uv sync --frozen --extra dev
uv run --frozen --extra dev pytest -q
uv run --frozen --extra dev ruff check src tests
uv run --frozen --extra dev ruff format --check src tests
```

The emulator, state parser, actions, and original direct Jev policy come from
[fhshaik/typesafe-mario](https://github.com/fhshaik/typesafe-mario), pinned to commit
`ca22449ed187118d19326d1f54b01b6636578aa4` and installed as a dependency.
The assisted experiment design is inspired by
[4esv/jev-mario](https://github.com/4esv/jev-mario).
No ROM files are included in this repository.

For implementation details, see the [Zoom API integration](docs/zoom-api.md) and
[reference evaluation](docs/reference-evaluation.md).
