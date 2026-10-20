# Zoom Decisions Mario blog package

Status: draft for author review. The blog has not been published to an external site.

- [Medium-ready article](medium.md): prose and captions adapted for Medium, with a separate cost discussion.
- [Browser copy](medium.html): open locally and copy the rendered article into a Medium draft. Upload the PNG images separately and retain their captions; the replay link can remain a link or be replaced with a hosted-video embed.
- [Article](article.md): approximately 1,600 words; integration, investigation, final outcomes, and limitations.
- [Results CSV](results.csv): eight provider rows, keeping each Jev pairing separate.
- [Source manifest](source-manifest.json): run IDs and hashes for uploaded configurations and summaries.
- [Animated GIF](assets/decisions-stage-1-1-replay.gif): complete replay at 480 pixels wide and 10 fps, looping with the original timing and on-screen labels. Upload directly as an image in the Medium results section.
- [Annotated replay](assets/decisions-stage-1-1-replay.mp4): standard Decisions, depth 1, seed 123, episode 1; 32 decisions and 1,822 gameplay frames, verified against recorded state digests.
- [Replay manifest](assets/replay-manifest.json): source-log hash and playback details.

The 32.37-second clip contains 30.37 seconds of simulated gameplay plus a two-second
final-frame hold. API and simulation waits are omitted and labeled on-screen. It
has no audio. Labels reflect executed recorded choices, not new API calls. The
runner verified the final emulator clear flag before creating the clip.

## Evidence and editorial checks

The source summaries record 40/40 Zoom clears and 39/40 Jev clears across the four
batches, no model-controlled deaths/API failures, and survival guard off. At depth 1,
all models clear 10/10 in each pairing. The table rounds mean simulation frames to
whole frames and decisions to one decimal. Times/latencies must not be presented
as uncontended service benchmarks: batch timestamps and durations indicate overlap.

The user-uploaded API Markdown reference supports the endpoint, model identifiers,
bearer authentication, scope, entitlement requirements, and choice response contract.
The article's API snippet is an integration illustration, not an independently
live-tested sample. No hosted-site access was required to inspect that supplied reference.

### Source provenance still unresolved

The uploaded runs record commit ee7581e1ca80fa23f63e43add60a79522507b551 and dirty=true.
The user's local source diff was not uploaded. A clean checkout here cannot establish
what local changes existed when those measurements were made. Do not silently change
the recorded provenance or describe these as exact clean-commit reproductions.

Before claiming exact reproducibility, retain the local diff from the experiment if
still available, or perform a clean-checkout confirmation run. If neither is available,
keep the disclosure already included in the article. The saved API requests and
replayed traces substantiate narrower behavior claims, not the missing source diff.

No broader benchmark is required for this one-stage engineering case study. Unseen
levels are future work. Do not frame this as an official Hugging Face benchmark,
raw-pixel agent evaluation, or proof that Pro universally beats standard Decisions.

## Regenerate the clip

Requires the original source JSONL, the matching repository environment, and ffmpeg
with libass/H.264 support. The private uploaded logs are not copied into this folder.
From the repo root:

```sh
uv run --frozen python docs/blog/zoom-decisions-mario/render_replay.py PATH_TO_ZOOM_001_JSONL /tmp/mario-blog-replay
```

Use the standard-Decisions depth-1 run `20261020T072748Z-ecc33471`. The script is
specific to standard-Decisions captions and rejects another returned model ID.
All before/after and final state digests must match; no API keys are required.

## Blog charts

- [Clear rates](assets/clear-rates.png): separate Jev pairings; observed counts, not projected success probabilities.
- [Lookahead trade-off](assets/lookahead-tradeoff.png): aligned panels for average decisions and simulation frames per Zoom episode, with zero-based axes.

Both are generated solely from `results.csv`; PNG is suitable for embedding and SVG
for scaling or editing. The article embeds the PNGs with descriptive alt text.
No new model calls or GUI runs were used. Rebuild without changing the app environment:

```sh
uv run --no-project --with matplotlib==3.10.8 python docs/blog/zoom-decisions-mario/render_charts.py
```

Depth-2 decision-count reductions are 6.2% (standard) and 13.9% (Pro); simulation-frame
ratios are 5.8x and 5.3x. The figures do not equate simulation frames to tokens, money,
or elapsed time. These repeated development-stage samples are not independent unseen
levels; the charts do not claim statistical superiority.
