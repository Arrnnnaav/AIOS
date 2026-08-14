# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

## Tech stack (decided, see DECISIONS.md D002–D005)

- **Platform:** Windows-first, not cross-platform (v1). Packaging with Tauri is a later,
  separate decision — don't introduce it into the core agent loop.
- **Language:** Python throughout the core agent (perception, overlay, reasoning, memory).
- **Perception:** tiered, cheapest-first — `pywinauto` (Windows UI Automation) first,
  `mss` + `PaddleOCR` for text-only fallback, a VLM pointing model (MolmoPoint-style)
  only as a last resort. Never run a VLM on every frame.
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
- **Reasoning:** an explicit state machine (`IDLE → OBSERVING → DECIDING →
  RENDERING_HINT → AWAITING_USER_ACTION → VERIFYING`), observe-act-**verify** rather than
  plain ReAct — a failed verification re-observes and re-plans from real state rather than
  blindly retrying, because the user can change the world between observation and action.
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
python -m tests.test_overlay        # 14 checks: styles, click-through, transparency,
                                    # hint placement, stale pixels, teardown
python -m tests.test_end_to_end     # 8 checks: perception -> coordinate -> ring on screen
python -m pytest tests/             # 112 checks: everything else (grounding, promotion,
                                    # persistence, verification, the state machine, ...)
```

`pytest` does not collect the two pixel harnesses above — they keep their own
runner because they assert against real Win32 window state and screen pixels,
not just Python state.

These assert against pixels and Win32 state, not appearance — run them instead of
asking a human whether the overlay looks right. Two rules they encode, both learned
from real bugs (D009, D010, D012 in DECISIONS.md):

- **Verify against a controlled backdrop** (`tests/backdrop.py`), never the live
  desktop — unrelated screen activity otherwise shows up as false differences.
- **Capture with `dpi.capture_region()`**, never `mss.monitors[1]`, and never from a
  separate process. A process with different DPI awareness captures a region that
  doesn't correspond to the desktop, which produces convincing but meaningless images.

Dependencies: `pywin32` (win32gui/win32con/win32api), `numpy`, `ollama`, `pywinauto`,
`mss` — installed via the system Python at
`/c/Users/user/AppData/Local/Programs/Python/Python312/python` (no venv set up yet).

## Repo layout

```
ghostcursor/
  run.py            # entry point for the current milestone
  overlay/          # Win32 layered/transparent window + GDI drawing (window.py)
  perception/        # UIA queries (uia.py) + app identity/version (appinfo.py);
                     # mss/OCR/VLM tiers not yet built
  reasoning/          # observe-act-verify state machine (loop.py), grounding ladder +
                     # promotion (grounding.py), verification, recipes, overlay renderer
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
