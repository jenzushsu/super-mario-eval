# Mario decision comparison

Two Super Mario Bros. episodes side by side: **TypeSafe Jev** and **Zoom Decisions**.
Uses [fhshaik/typesafe-mario](https://github.com/fhshaik/typesafe-mario) at commit
`ca22449ed187118d19326d1f54b01b6636578aa4` for the emulator, state parser, actions,
and unmodified Jev policy. Upstream source is installed as a dependency, not copied.

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
seven-predicate request remains unverified until this succeeds with your key.

### 5. Open the live side-by-side comparison

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
  summary. The adapter assumes the predicate response format in
  [docs/zoom-api.md](docs/zoom-api.md); additional API compatibility work may be
  needed if the live service differs. Do not treat this as a model score.
- **No display / video device:** run from a desktop session or add `--headless`.
  To capture an offline frame on a headless macOS/Linux environment:

  ```sh
  SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run --frozen mario-eval \
    --offline --max-decisions 10 --exit-when-done --screenshot artifacts/comparison.png
  ```

## Comparison methodology

- Same level, seed (123), seven legal actions, parser, and eight emulator frames per action.
- Two independent episodes; states diverge after the models choose different actions.
- Requests run concurrently. Both emulators pause during inference, then advance in
  lockstep. Latency is recorded but does not impose a gameplay penalty. This is a
  decision-quality comparison, not the upstream real-time latency-sensitive mode.
- Jev retains its native Choice, Noul and Score request. Zoom asks seven independent
  predicates, one per candidate action, and selects the highest probability.
  Ties use the shared action order. Predicate scores are **not normalized** and
  must not be interpreted as a categorical distribution or compared directly
  with Jev confidence. Jev's extra judgments also affect latency comparability.
- Zoom receives text JSON, no screenshots, matching Jev's information source.
  The supplied Zoom examples demonstrate one predicate with text and an image;
  text-only multi-predicate acceptance still requires live API verification.
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
