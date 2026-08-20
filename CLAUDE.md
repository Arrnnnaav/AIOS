# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Knowledge Graph (Graphify)
Before answering any architecture question or searching for a file, read
`graphify-out/GRAPH_REPORT.md` if it exists. It contains god nodes (highest-degree
concepts everything routes through), community clusters, and surprising cross-file
connections. Use `/graphify query <term>` for precise traversal. This reduces token
cost dramatically — navigate the graph, don't grep raw files.

Re-run `/graphify .` after completing each major build step to keep the graph current.


## What this project is

This repo is building **Ghost Cursor**: a real-time, on-screen guide agent for Windows —
a lightweight always-on desktop app that watches what's on the user's screen, figures out
the next action toward a stated goal, and shows the user where to click/type via a
transparent overlay, instead of a chat window. It is Phase 1 ("Teach") of a larger,
longer-term "AI Operating System" vision described in `My idea.docx` (a persistent AI
layer that teaches, onboards, supports, collaborates with, and eventually operates
software on the user's behalf). Ghost Cursor is the concrete, buildable wedge of that
vision — not the whole thing. See `My idea.docx` for the full vision/market research if
context on the "why" beyond this phase is needed.

Ghost Cursor is architecturally distinct from both a chatbot-with-screenshots (text only,
one screenshot per turn) and an autonomous computer-use agent (acts for the user). It
sits in between: a continuous perception → reasoning → rendering loop that shows the user
where to act but never acts for them (see D006 in DECISIONS.md — this is a hard safety
boundary, not a v1 shortcut).

## Required reading before building any subsystem

Before writing perception, overlay, reasoning, memory, or inference code, check
`D:\tracker\docs\ghostcursor\` for an existing note on the topic — this project has a
full doc set already written (UIA fundamentals, pywinauto, mss, PaddleOCR, MolmoPoint,
Win32 layered/transparent overlays, GDI drawing, PyAutoGUI safety, state machines,
OSWorld/AndroidWorld agent-loop patterns, SmolLM, SSE streaming, Tauri packaging/
permissions/updater, entity-scoped memory, the Clippy UX post-mortem, and a full
OpenClicky architecture reverse-engineering doc). The single most important doc is:

`D:\tracker\docs\ghostcursor\build-the-ghost-cursor-mvp-screen-perception-overlay-reasoning-loop-local-inference.docx`

— it's the capstone build doc this whole project follows, with a complete checklist and
three build tiers (Beginner → Intermediate → Resume-level MVP). When a doc from that
folder informs a decision, cite it in `DECISIONS.md`.

Two other tracking files are living documents, updated on every meaningful change:
- **`DECISIONS.md`** — what was decided, what the alternatives were, and why. Read this
  first when picking up work — it has the reasoning already worked out, don't re-decide.
- **`FLOW.md`** — how execution actually travels between files/functions right now, plus
  a "you are here" marker showing exactly what's built vs. planned. Update it whenever
  the call graph changes, not just at the end of a milestone.

## Standing rules — read before doing any work

Five process rules, each adopted after a measured failure on this project, not
written speculatively. They are scattered through DECISIONS.md by number; this
is the index, because a rule nobody can find is not enforcing anything.

| Rule | What it requires | What it cost to learn |
|---|---|---|
| **D018** | Mutation-verify safety-critical properties: break the code deliberately, confirm a test notices. | A passing suite hid three vacuous tests. |
| **D026** | Stateful or time-based behaviour gets an ordered-sequence test on an injected clock, never end-state assertions. | Every component correct in isolation while the assembled system did nothing — twice. |
| **D031** | State the property a fix protects AND the invariant enforcing it, then say whether the invariant *implies* the property or merely correlates with it. | Four separate "false greens", most sharply a one-write-per-tick counter that held perfectly while a pixel guess was painted in the confirmed-control colour. |
| **D032** | **ENFORCED GATE.** Nothing the controller authored or asserted — code, prose, documentation, or a figure written into a dispatch brief — is ground truth until something else has read it. | Two occurrences on one milestone: three of four documentation defects in the one self-reviewed slice, then an uncited number reaching the docs as fact. |
| **D034** | A measured number in documentation must name where it is recorded. If it exists only in a session or a scratch run, record it first or do not present it as evidence. | An unrecorded-but-real measurement was cited as spike-sourced, with an inverted justification pointing toward lowering a safety floor. |

### Dispatching work to subagents

**Instruct every implementer to commit as soon as its tests pass, before any
mutation or verification work.** Five agents were lost to capacity limits
mid-task during one milestone. Every one that had committed early kept its work;
the one that had not lost a full task, and a second died before writing a single
line. For read-only work — reviews, audits — the equivalent is to write findings
to a scratch file incrementally rather than reporting only at the end.

This is cheap, and it is the single instruction with the best measured
return of anything tried on this project.

## Tech stack (decided, see DECISIONS.md D002–D005)

- **Platform:** Windows-first, not cross-platform (v1). Packaging with Tauri is a later,
  separate decision — don't introduce it into the core agent loop.
- **Language:** Python throughout the core agent (perception, overlay, reasoning, memory).
- **Perception:** tiered, cheapest-first — `pywinauto` (Windows UI Automation) first,
  then OCR on captured pixels, then a VLM pointing model (MolmoPoint-style) only as a
  last resort. Never run a VLM on every frame.
- **Tier 2 (OCR), see D028-D030:** the engine is **`Windows.Media.Ocr`**, not PaddleOCR —
  0.17-0.23s per window against RapidOCR's 39-66s, and it ships with the OS, so there is
  no model download and no network (D017). It is triggered by **grounding failure for the
  current step, outside a new window's warm-up** (D035) — a `WarmUp` keyed by window handle
  suppresses the tier-2 request for a budget (`DEFAULT_WARMUP_BUDGET_S = 2.0`) after a
  window's first failed grounding, so a cold Chromium accessibility tree gets a chance to
  populate before OCR engages — never by an empty walk: Chrome returned 43 UIA elements containing zero
  page content, so "UIA returned nothing" would never fire. **The UI thread decides and
  requests; the perception worker executes and publishes.** Only the tick loop knows which
  step is current and whether grounding just failed, so it sets a `Tier2Request` in a
  single overwritten request slot (`PerceptionService.request_tier2` /
  `cancel_tier2` / `report_tier2_grounded`) — a lock-and-assign that never blocks and never
  waits. The worker performs the capture and the OCR read on its own thread and publishes
  the result as `ocr_elements` on a *later* `Observation`; capture plus OCR measured
  0.14-0.23s on a 976x1028 window and scales with captured area, which on the tick path
  would eat D020's 0.5s ceiling and reintroduce the D021 freeze. Absence of a request means
  "not wanted" — there is no `wanted` flag — so the UI thread must cancel when grounding
  succeeds without OCR and at every step boundary. Stickiness resets at the step boundary, a
  1.0s floor and a ceiling of **20 consecutive fruitless runs** (reset by a read that
  grounds) bound the cost, and exhausting that ceiling ends the step rather than freezing a
  hint that can never resolve. OCR text reaches grounding at rung 4 on a fuzzy match at a
  **measured floor of 95**, and at rung 2 on byte-exact name equality — a strictly higher
  bar, so it never undercuts the floor. Rung 3 is a substring test and is the one rung OCR
  is barred from, or the floor would be decorative. **Nothing OCR produces is ever persisted**:
  `promote()` in `ghostcursor/reasoning/grounding.py` guards explicitly on the grounded
  target's provenance and refuses anything not sourced from a confirmed UIA control. That
  guard used to be redundant with OCR elements simply lacking an AutomationId, but that was
  "never promoted by construction" resting on a coincidence of empty strings, not a real
  barrier — a future tier (the VLM, tier 3) could supply a non-empty id, and the empty-id
  check alone would stop covering that case. The explicit provenance guard is what actually
  closes it now, and `tests/test_regression_ocr_fixes.py` isolates it. OCR-derived
  hints render in their own colour (`INFERRED`) so a pixel guess never wears the
  confirmed-control ring (D006).
- **Overlay:** raw `win32gui`/`win32con`/`win32api` (pywin32) — `WS_EX_LAYERED |
  WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW`, colorkey transparency via
  `SetLayeredWindowAttributes`, GDI for drawing. The overlay must always stay click-through
  and must never move the real OS cursor or synthesize input (D006 — hard safety rule).
  **All drawing happens inside `WM_PAINT`** (D009): the handler fills the whole client
  area with the colorkey and then draws the hint. Never draw from the polling loop via
  `GetDC` — that leaves the window surface uninitialised, which renders as an opaque
  wash over the entire screen instead of transparency.
- **Coordinates:** import `ghostcursor.overlay.dpi` before creating any window (D010).
  It declares DPI awareness at import, which pins one coordinate space for window
  rects, UIA rects, hints and screen captures. Skip it and `GetSystemMetrics` silently
  changes its answer mid-run the first time anything takes a screenshot.
- **Threading:** perception runs on a **worker thread**, never on the UI thread
  (D021). The worker calls `CoInitializeEx` and owns its `Desktop()` entirely —
  UIA objects are apartment-bound, and passing one across threads gives
  confusing intermittent failures rather than a clean error. Only frozen
  dataclasses of primitives cross the boundary (`Element`, `Snapshot`, the
  timestamp); no COM object, ever. The worker publishes into a **single
  timestamped slot** by overwriting (D022) — no queue, no history, no futures.
  The UI thread reads that slot without ever blocking, so it keeps pumping
  messages and polling ESC no matter how slow perception becomes. This is not
  optimisation: a "Not Responding" target blocks one UIA walk for **41 seconds**
  measured, and ESC is polled between ticks, so on the UI thread that is 41
  seconds the user cannot dismiss a window covering their whole screen. UIA
  exposes no timeout, and a watchdog cannot help — verified, `DestroyWindow`
  from a non-owning thread returns `Access is denied`.
- **Reasoning:** an explicit state machine (`IDLE → OBSERVING → DECIDING →
  RENDERING_HINT → AWAITING_USER_ACTION → VERIFYING`), observe-act-**verify** rather than
  plain ReAct — a failed verification re-observes and re-plans from real state rather than
  blindly retrying, because the user can change the world between observation and action.
  `AWAITING_USER_ACTION` also names a wrong action: if verification is unsatisfied and UI
  Automation focus visited a control other than the step's grounded target, the loop prints
  what was touched and re-asserts the hint via `OBSERVING` (see D037). The signal is focus,
  not element churn — element identity was measured drifting with no user action at all —
  and it is silent on OCR-grounded steps, which carry no AutomationId to compare against.
- **Local inference:** small local model on the hot path (SmolLM-class via Ollama,
  sub-second budget, streamed and parsed incrementally), a larger local model reserved for
  rare/complex reasoning.
- **Memory:** entity-scoped (`user_id, app_id, concept`), not per-conversation — SQLite.

## Running the current milestone

```
cd D:\PROJECTS\AIOS
python -m ghostcursor.run                  # targets Notepad; open it first
python -m ghostcursor.run --target Chrome  # any window title (regex)
python -m ghostcursor.run --seconds 30     # auto-stop sooner
```

**Press ESC to quit.** The overlay is full-screen, topmost and click-through, so it
has no title bar and never takes focus — ESC (polled, works from any app) and the
`--seconds` timeout are the only ways to stop it. Never remove either; a rendering
bug in a window the user cannot close is how this locks someone out of their machine.

## Stored data

Ghost Cursor keeps a local knowledge base of what grounding has learned: UI
AutomationIds and their control types, keyed by step, app, and app version,
plus the app identity (`app_id`, `app_version`) used to look them up. Only
`python -m ghostcursor.run --recipe <path>` (the guided-tour path) populates
it — grounding during a tour promotes what it learns and persists it via
`ObservationStore`, and the next `--recipe` run against the same app
hydrates the recipe's steps from what was learned before. It is
written by `ghostcursor/memory/store.py`'s `ObservationStore` to
`%LOCALAPPDATA%\GhostCursor\kb.sqlite`, and only ever there — no telemetry,
no network, no cloud sync (D017 in DECISIONS.md). `GHOSTCURSOR_KB_PATH`
overrides the path, which is how tests and multi-process verification use a
scratch database instead of the real one. Deleting the file erases the
knowledge base entirely; the system simply re-learns from scratch on the
next run, exactly as it would on a first run.

## Tests

```
python -m tests.test_overlay        # 16 checks: styles, click-through, transparency, hint
                                    # placement, dimmed and inferred ring colours, stale
                                    # pixels, teardown
python -m tests.test_end_to_end     # 8 checks: perception -> coordinate -> ring on screen
python -m pytest tests/ \
  --ignore=tests/test_hung_window.py \
  --ignore=tests/test_perception_service_hung.py \
  --ignore=tests/test_run_threaded.py   # 280 checks, ~22s: everything fast (grounding,
                                    # promotion, persistence, verification, staleness,
                                    # worker health, OCR, the state machine, ...)
python -m pytest tests/test_hung_window.py \
                tests/test_perception_service_hung.py \
                tests/test_run_threaded.py     # 13 checks, ~128s: the hung-target tests.
                                    # Run these ALONE — never beside another pytest session
```

`pytest` does not collect the two pixel harnesses above — they keep their own
runner because they assert against real Win32 window state and screen pixels,
not just Python state.

**Never run two test sessions at once, and never run the hung-target tests
alongside anything else** (D025). Those three files park a real non-pumping
window on the desktop, and any UIA enumeration that touches such a window pays
the SendMessage timeout no matter which *process* started the walk. Measured:
the same two UIA-dependent files take **6.28s on a clean desktop and 100.13s**
with one hung window up. Timing-marginal tests then fail for reasons that have
nothing to do with the code, and get misreported as pre-existing flakes — which
has already happened here twice.

These assert against pixels and Win32 state, not appearance — run them instead of
asking a human whether the overlay looks right. Two rules they encode, both learned
from real bugs (D009, D010, D012 in DECISIONS.md):

- **Verify against a controlled backdrop** (`tests/backdrop.py`), never the live
  desktop — unrelated screen activity otherwise shows up as false differences.
- **Capture with `dpi.capture_region()`**, never `mss.monitors[1]`, and never from a
  separate process. A process with different DPI awareness captures a region that
  doesn't correspond to the desktop, which produces convincing but meaningless images.

Dependencies: `pywin32` (win32gui/win32con/win32api), `numpy`, `ollama`, `pywinauto`,
`mss`, plus the tier-2 stack — `winsdk` (the `Windows.Media.Ocr` binding), `Pillow` (the
PNG encode `BitmapDecoder` is fed from), and `rapidfuzz` (rung 4's `fuzz.ratio`). Without
those three the OCR tier cannot run at all. Installed via the system Python at
`/c/Users/user/AppData/Local/Programs/Python/Python312/python` (no venv set up yet).

## Repo layout

```
ghostcursor/
  run.py            # entry point for the current milestone
  overlay/          # Win32 layered/transparent window + GDI drawing (window.py)
  perception/        # tier 1: UIA queries (uia.py) + app identity/version (appinfo.py);
                     # the worker thread and its published slot + tier-2 request slot
                     # (service.py) and worker-death detection (health.py);
                     # tier 2: mss window capture/diffing (capture.py), Windows.Media.Ocr
                     # (ocr.py), cadence and caps (tier2.py) — built and wired.
                     # Tier 3 (VLM) not yet built
  reasoning/          # observe-act-verify state machine (loop.py), grounding ladder +
                     # promotion (grounding.py), verification, staleness ladder
                     # (staleness.py), recipes, overlay renderer
  memory/             # SQLite knowledge base of learned observations (store.py); see "Stored data" above
  inference/           # local model streaming/decision — not yet built
DECISIONS.md   # why — read first
FLOW.md         # how execution flows, "you are here" marker
My idea.docx    # the full long-term vision + market research (context, not a build doc)
```

## A note on scope discipline

The build doc's checklist is large (perception tiers, overlay, reasoning loop, local
inference, memory, packaging, safety/UX, end-to-end). Work through it in the order the
doc lays out — Beginner → Intermediate → Resume-level MVP — rather than jumping ahead to
later-phase features (adaptive interfaces, cross-app workflows, the full AIOS vision).
Every later phase is a superset of this loop; building it out of order means re-doing
foundational work later.
