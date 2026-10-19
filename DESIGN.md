# Comparison display

Extend the upstream desktop telemetry dashboard's restrained dark palette.
Two equal 512×480 game feeds are the primary content, with provider/method labels
above and status, action, progress, reward and latency beneath. Show shared level,
seed and simulation mode above both lanes. Use explicit OFFLINE labels on smoke
tests. No decorative assets or charts. Typography uses installed DejaVu Sans.

Canvas: #0f1115. Primary text: #eceff3. Secondary text: #acb6c4.
Window: 1120×760; outer inset 32; lane pitch 552. Body 17px, small 14px,
titles 26px. Native desktop fixed layout; not a browser or mobile surface.
Keyboard: Q/Escape closes. Finished episodes remain visible until closed.

Assisted mode inherits this desktop layout. The subtitle identifies which policy
is currently simulating, waiting, or executing; search runs appear in the report
while the two primary panels remain Jev and Zoom. Offline fixtures are explicitly
named in both headers. No new visual system or browser surface is introduced.
