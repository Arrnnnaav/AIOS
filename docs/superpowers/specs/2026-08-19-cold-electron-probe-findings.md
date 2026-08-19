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

---

# Addendum — Discord, 2026-08-20

Added because §5 above named Discord as untested. Discord 1.0.9254, logged in,
one machine. Probe scripts were throwaway and are not in the repo; every number
below is from a run recorded in this section.

## 6. A second Electron app agrees — but only once the splash is excluded

Discord was chosen deliberately, not as "another Electron app". VS Code loads
its content from the local filesystem, so the earlier finding that nothing
grounds slowly-but-eventually could have been an artifact of there being nothing
to wait for. Discord loads its server, channel and member lists over the
**network** after the window appears. If a slow-but-eventual element existed
anywhere, this was the place it should have shown up.

### 6.1 Warm process, cold accessibility tree

Discord already running, no UIA client having touched it, polled every 0.2 s:

| t | elements | content | named | walk |
|---|---|---|---|---|
| 0.00 | 7 | 0 | 1 | 0.082 s |
| 0.28 | **134** | **53** | **98** | 0.179 s |
| 0.66 → 20.0 | 134 | 53 | 98 | ~0.18 s |

The tree is built in **one poll, under 0.28 s**. Zero names appeared after 0.5 s.
Zero non-monotonic drops over 53 samples; walks median 0.180 s, max 0.20 s.

The zero drops matter for §3: VS Code fluctuates in steady state, Chrome on a
static page does not, and Discord — busy, network-fed, and Chromium — does not
either. That is a third data point for the fluctuation being **one app's UI
churn rather than a property of Chromium's accessibility tree.**

### 6.2 Two cold launches that measured the wrong window

Cold launches matching `.*Discord.*`, the obvious regex:

| Run | First matching window | Targets grounded | After that window |
|---|---|---|---|
| A | 2.01 s | `Settings`, `Friends`, `Inbox`, `Add a Server` | **7.49 s** |
| B | 1.00 s | same four | **9.98 s** |

Taken at face value this **falsifies a 2.0 s budget outright.** It does not,
and the reason is the finding of this addendum.

### 6.3 The cause: a splash window with its own HWND

Both runs showed 10 elements / 3 content sitting flat for ~7 s before jumping to
92/33 in a single poll. A dedicated probe resolved it:

| HWND | title | first seen | last seen |
|---|---|---|---|
| 329088 | `'Discord Updater'` | 1.51 s | 6.58 s |
| 1638728 | `'Discord'` | 6.58 s | 24.51 s |

**Two distinct top-level windows.** The flat period was the updater splash,
which matches `.*Discord.*`, is visible, non-minimised and on-screen, and so
satisfies `windows_matching` completely. Runs A and B measured the updater's
lifetime and attributed it to the accessibility tree.

### 6.4 Measured from the real window

Re-run with `^(?!Discord Updater).*Discord`:

| Target | Grounded after main window |
|---|---|
| `Settings`, `Friends`, `Inbox`, `Add a Server`, `Discover`, `Direct Messages` | **0.92 s — all six, same poll** |

7 elements / 0 content at the first two polls, then 92/33 at 0.92 s and 95/33
thereafter. A **1.0 s budget already covers every target**; 2.0 s has margin.

"55 of 56 names first seen more than 0.6 s after the window" is the same single
jump at 0.92 s, not a trickle of late arrivals — recorded explicitly because the
raw figure invites the opposite reading.

Walks: median 0.719 s, max 1.59 s, 4 of 27 over 1 s — slower than VS Code's
0.413 s median but nowhere near HIDDEN, consistent with §4.

### 6.5 What this changes

1. **The 2.0 s budget survives a second, architecturally different application.**
   Network-loaded content did not arrive late; it arrived with the window.
   "Either it grounds within ~1 s or waiting does not help" now has two apps
   behind it, one of them the case built to break it.
2. **A splash or updater window that matches the target title is a real defect
   for a warm-up keyed to the title regex.** Discord's updater would consume the
   entire budget before the real window exists, leaving the real window with no
   allowance and escalating to tier 2 immediately — exactly the failure warm-up
   was built to prevent. This was found by measurement, not review.

## 7. What the Discord runs still do not establish

- One machine, one account, one Discord version, warm network, already logged
  in. A first-run login flow was not measured.
- §6.4 is a **single** run. §6.2's two runs are not confirmation of it — they
  measured a different window.
- Whether other applications ship a title-matching splash is unknown; Discord is
  an existence proof, not a frequency estimate.
