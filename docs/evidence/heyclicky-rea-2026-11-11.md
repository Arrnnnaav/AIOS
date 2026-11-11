# HeyClicky for Windows: UI and interaction layer (11 November 2026)

Same installer as `heyclicky-rea-2026-10-28.md` (v1.1.1, signer Humansongs,
Inc), re-carved into a scratch folder; nothing installed or run. That pass
read the agents DLL; this one reads the UI layer.

Method: REA `inspect_managed_artifact` on `HeyClicky.Drawing.dll`
(sha256 `7ee5b461...d1a1d8`, .NET 9 ReadyToRun, metadata complete, 290
types, 2181 methods). Identifier names in `HeyClicky.Drawing.dll` and
`HeyClicky.dll` were then listed with a stdlib scan (names only, read as
data). Behaviour below is inferred from names, not decompiled bodies.

## Interaction model the names describe

- A coloured cursor companion (`CursorColorOption`: blue/green/red/yellow)
  docked next to the pointer (`DockedCursor`, `DockedIdle`), with idle life
  (`AnimatesWhileIdle`, `BlinkOnce`, `BlinksOnPointerEntry`).
- Push-to-talk (`BeginPushToTalkAsync`/`EndPushToTalkAsync`) and three
  visible states: `ActivityListening`, `ActivityThinking`, `ActivitySpeaking`.
- The companion flies to what it is talking about on a spring
  (`AnimateSpringVector2`, `SpringStiffness`, `SpringDamping`,
  `SpringSettlingSeconds`, `FlyAsync`) and marks it with a halo/glow
  (`HaloBrush`, `GlowRadius`, `AddEdgeGlow`).
- Live captions in a tailed bubble (`ShowLiveCaption`, `BubbleTailDrop`) and
  a "you said" slip (`ClickyInkYouSaidSlip`).
- Results fold into a top-of-screen notch (`FlyIntoNotch`, `TryPeek`,
  `DismissNotchAgentPeek`) as hand-drawn "ink" cards (`ClickyInk*`, ~250
  card/figure types: receipts, tickets, tallies, streaks, timelines).

## Already in Orbyn before this pass

Island notch with peek-on-hover and result cards (D190/D191), hold-to-talk
with a Listening state, a breathing halo (`cue.pulse_delta`), Teach speaking
while it draws (D189).

## What Orbyn took

- The ring now flies from the user's cursor (or from where it was) to the
  observed control with a spring ease-out and lands exactly on it
  (`cue.fly_position`, `FLY_S` = 0.45 s, moves under `FLY_MIN_PX` snap). A
  15 ms timer only invalidates; painting stays in WM_PAINT (rule 4). Pinned by
  `tests/test_cue_flight.py`; desktop runs: `tests.test_overlay` 16/16,
  `tests.test_end_to_end` 8/8, pixel lane 3/3, interactive lane 85/85 on
  this machine, 11 November 2026.

## Not taken

- Companion that rests beside the pointer all the time: needs an always-on
  overlay presence; noted for FOLLOWUPS.
- A drawn pointer at a model-supplied point (Clicky's `PointAt`): rule 3.
