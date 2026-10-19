# Mario decision comparison

Two Super Mario Bros. episodes side by side: **TypeSafe Jev** and **Zoom Decisions**.
Uses [fhshaik/typesafe-mario](https://github.com/fhshaik/typesafe-mario) at commit
`ca22449ed187118d19326d1f54b01b6636578aa4` for the emulator, state parser, actions,
and unmodified Jev policy. Upstream source is installed as a dependency, not copied.

## Run

Python 3.13 and uv are required.

```sh
uv sync --frozen --extra dev
# Configure TYPESAFE_API_KEY and ZOOM_API_KEY securely in your environment.
uv run --frozen mario-eval
```

The desktop display stays open at the end; press Q or Escape to close it.
This cloud environment does not expose the desktop window in your local browser.
Use headless mode here, or capture a frame with SDL's dummy display:

```sh
uv run --frozen mario-eval --headless --max-decisions 250
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy uv run --frozen mario-eval \
  --offline --max-decisions 10 --exit-when-done --screenshot artifacts/comparison.png
```

`--offline` uses **two heuristic policies**, clearly labeled in the display and
run configuration. It validates the harness and makes no model API requests.
It is not evidence of Jev or Zoom performance.

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
