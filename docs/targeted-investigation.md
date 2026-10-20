# Targeted trap and stall investigation

The user-supplied nine-case evaluation used corpus SHA-256
`a8ec7f5edd3ed5ea9377a08cc0aea582cd23bffa925126de303228031a088347`.
All 36 live calls completed; submitted evidence matched across Jev and Zoom.
Standard Decisions selected run_jump at Pro D13; Pro selected hop. Both selected
hop, jump, walk at D14–D16 when presented with Pro's trajectory. Both Zoom variants
selected advancing run_jump at all three Jev stall checkpoints; Jev selected
wait/walk/run with zero displacement. Existing survival guard would override none
of these recorded choices.

## Deeper emulator investigation

We reconstructed Pro D13–D16 from recorded prefixes and explored an additional
seven-action follow-up layer. This uses no model calls and makes no claim about
model reasoning or eventual stage completion.

| Checkpoint | Finding |
| --- | --- |
| D13, x1497 | Both run_jump and hop have surviving three-move paths; hop is not inherently fatal. Best observed three-move displacement: run_jump 373, hop 337. |
| D14, x1622 | Hop still has surviving three-move paths. |
| D15, x1712 | Several moves retain surviving paths. |
| D16, x1823 | Walk has zero surviving three-move paths. Wait has seven; best observed path wait → walk → run_jump advances 176 pixels. |

The extra horizon exposes a distinction the previous two-move evidence misses.
It does not establish that the API will choose wait or that waiting guarantees a clear.

## Shared implementation experiment

- Prompt `outcome-ranker-v6`; evidence `progress-cycles-v2`.
- Immediate displacement, endpoint gain and stage completion are explicit.
- Hypothetical follow-up progress is marked as requiring another decision.
- Repeated zero-progress choices should yield to an immediately advancing viable
  alternative; survival remains the higher priority.
- Optional depth 2 exposes compact three-move path summaries. Depth 1 remains the
  default. All expanded nodes test the same seven actions, with terminal pruning.
- Unknown paths stay distinct from surviving and fatal paths. Counts are not probabilities.
- No automatic moves, new guard rule, or deterministic search scoring change.

The targeted regression fixtures retain controller inputs/history, not ROM files.
Tests reproduce the D16 wait route, verify depth-1 outcomes remain unchanged under
extra exploration, check restoration after budget exhaustion, and distinguish
hypothetical progress from immediate progress at Jev's stall.

## Evaluation sequence

1. Retain the original v5 run folders as baseline.
2. Rebuild the same nine checkpoints with v6/depth1 and v6/depth2 evidence.
3. Evaluate Jev versus each Zoom variant on both corpora (four evaluations).
4. Compare choices and fatal/unknown continuation evidence case by case; report
   simulation frames, API input usage and latency alongside results.
5. Freeze the selected settings before evaluating new, held-out trajectories and
   levels. These nine failure-selected cases are development data, not held-out results.

Live improvement remains unmeasured until these updated evaluations run. Cloud
access previously returned Jev HTTP 401 and Zoom HTTP 403; offline tests are not
substitutes for model measurements.
