# Cold Electron Start — Probe Findings

Date: 2026-08-19
Status: measurement complete; input to the Chromium warm-up retry design
Probe code: throwaway, not kept (scratchpad `cold_electron_probe*.py`)

Three cold starts of VS Code (Electron/Chromium), walked via `iter_elements`
every 0.25s from the instant the window appeared. The probe's own first walk is
what asks Chromium to build its accessibility tree — which is exactly the
production situation, since Ghost Cursor's perception worker is the first UIA
client to touch the target.

| Probe | Workload | First read | Content stabilises |
|---|---|---|---|
| 1 | real workspace, extensions restored | 14 elements, 1 content | 5.25s (146 / 38) |
| 2 | isolated instance, empty folder | 13 elements, 0 content | 5.62s (220 / 45) |
| 3 | isolated instance, real project folder | — | ~5s (288 / 83) |

## 1. The cold signature is robust

Across probes 1 and 2 the first read after the window appears is **13-14
elements of pure window furniture**, and content takes **~4-5 seconds** to
settle. That part is consistent.

## 2. "Furniture present, no content" CANNOT distinguish not-yet-ready from
genuinely empty

This kills the obvious readiness test. A snapshot threshold cannot work at any
value, because a permanently-empty app produces the same shape:

| | elements | meaning |
|---|---|---|
| cold VS Code, first read | 13-14 | **transient** — content arrives in ~4s |
| Adobe Acrobat, always | 20 (17 anonymous Panes, 0 of 16 tool labels) | **terminal** — measured in the tier-2 spike |

Same shape, opposite meaning. **The discriminator has to be change ACROSS
probes** — does the tree grow when asked again? Acrobat's will not; Chromium's
grows by an order of magnitude.

## 3. The element count is NOT monotonic, and NOT stable even in steady state

Probe 1 saw one drop and probe 2 saw none, which suggested a workload-dependent
startup artifact. Probe 3, on a real project folder, **reproduces it four times
— including twice long after the ramp finished**:

```
 4.17s  210/59  ->   4.70s  175/34     during the ramp
 9.83s  263/73  ->  10.41s  165/44     during the ramp
19.58s  288/83  ->  20.29s  259/68     STEADY STATE
31.35s  291/94  ->  32.00s  289/93     STEADY STATE
```

So a live Electron app's UIA tree fluctuates continuously — roughly 10% swings
in element count — not just while starting.

**Design consequence:** "the count went up, so we have converged" is unsound,
and so is "the count stopped changing, so we are ready". Neither holds under a
real workload. Probe 2's empty folder was stable and therefore misleading; a
readiness rule validated only against a quiet app would pass and then misfire in
the field.

## 4. Slow walks are real but milder than first measured

Probe 1 recorded individual walks of **7.30s and 6.46s** against a warm, healthy
VS Code, which suggested the staleness ladder could be driven to HIDDEN (5s
threshold) by walk duration alone on an ordinary app.

Probe 3 does not support that:

```
median walk            0.413s
walks over 1.0s        5 of 40
walks over 5.0s        0
slowest                2.49s
```

The difference: probe 1 ran with a second VS Code instance open and after heavy
OCR work in the same session. So the 6-7s figures reflect a loaded machine, not
a baseline property of walking a healthy Electron app.

**Corrected position:** slow walks exist and spike to ~2.5s under ordinary
conditions, which is enough to reach DIMMED (1.5s) but not HIDDEN (5s). Under
additional system load they can reach 6-7s and would reach HIDDEN. This is a
watch item, not a confirmed defect — and the earlier claim that a healthy app
routinely trips HIDDEN is NOT supported by the measurements.

## 5. What this does not establish

- Only one application was measured. VS Code is Electron; Slack, Discord and
  Teams were not tested and may ramp differently.
- The 6-7s walks were observed once, under load whose composition was not
  controlled. The cause is unknown and may be probe-induced hammering at a
  0.25s poll gap.
- Nothing here measures a native app's cold start; Acrobat's numbers come from
  the tier-2 spike and are steady-state, not cold.
