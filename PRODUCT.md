# Product

A Python desktop and headless evaluation harness for comparing TypeSafe Jev and
Zoom Decisions controlling Mario. Users need to see both gameplay trajectories
and inspect reproducible logs. Live results must be distinct from offline smoke
tests. The user supplied Zoom request/response examples; no official documentation
was provided. The upstream Python controller is the shared baseline.

Assisted mode adds shared finite-horizon outcome simulation, two live provider
rankers, and a search-only baseline. Separate identical-state and episode reports
explain progress, errors, and simulation assistance. Native checkpoint restoration
and JSON action replay support reproducibility. Direct mode remains distinct.

Both direct and assisted episode modes run independent parallel lanes. A slow
provider cannot hold the other lane at a shared decision barrier. Each emulator
pauses for its own inference; desktop rendering stays on the main thread.

Real-time mode is a separate latency-sensitive track: live emulators keep stepping
while isolated planner emulators and providers work on older snapshots. It reports
decision age and bootstrap/held controls; it must not share a leaderboard with
paused assisted evaluation.
