# CLAUDE.md

## Current build status

The Open Track submission baseline and accepted terminal slice are merged on
`submission/open-track`. The terminal slice was developed from
`stable-pre-terminal` on `feature/vscode-open-terminal` and merged only after
its 3/3 gate and independent review. The trusted planner, strict application
packs, bounded screen-aware hint inference, synthetic demo, foreground watcher,
perception health instrumentation, executable-bounded VS Code grounding, and
vertical Ask control rail are implemented.

The submission inference implementation is anchored by
`submission-pre-model-hardening` at `15f20cef...` (D061). Do not merge or
cherry-pick `post-submission/model-durability` before submission. Its commit
`304e8e0` contains an explicitly incomplete structured-Ollama request slice;
`ghostcursor/inference/ollama.py` and its four added contract tests must remain
absent from the release branch. Release recertification passed 23 focused
planner/screen-hint tests, 361 hermetic tests, and the complete live eight-cell
never-fabricate matrix on the tagged code.

`OPEN_FOLDER` points at the Welcome page's `Open Folder...` action. The user
handles the native folder picker, and title verification supports full-path
goals, case-insensitive whitespace-normalized matching, degenerate-reference
fallback, and a 20-second post-action timeout. The workflow passed three
consecutive real-desktop runs. Ask passed visual, text-entry, submitted-goal,
trusted replanning, and completion validation. Installer, tray, startup,
web retrieval, and additional application packs remain deferred. The
logging-only watcher is available as `py -3.12 -m ghostcursor.daemon`.

`OPEN_TERMINAL` is the second validated VS Code intent. Its trusted recipe
highlights `Toggle Panel (Ctrl+J)`, tells the human to press `Ctrl+\``, and
accepts an already-visible exact `Terminal Section` before rendering. Otherwise
it verifies an absent-to-present state within 20 seconds of the first hint;
timeout wins over a state first observed after the deadline.
It passed 3/3 consecutive real-desktop runs. A click recipe is forbidden for
this goal because Toggle Panel restores whichever panel was active and opened
Debug Console during the measured rehearsal.

The deterministic planner aliases `VS Code`, `VSCode`, and
`Visual Studio Code` for both registered VS Code intents. The documented goals
`Open a folder in VS Code` and `Open the integrated terminal in VS Code` are
0.95 exact strong phrases and must continue to load their trusted recipes
under `MODEL_UNAVAILABLE_FALLBACK` when Ollama times out or is offline. Do not
rely on a folder name containing `vscode` to prove the folder route; the
regression fixture deliberately uses an unrelated folder name.

Never execute a model-selected available intent unless it agrees with the
deterministic classifier's grounded intent for the same goal (D058). A
registered ID is an allowlist boundary, not semantic evidence. On mismatch,
use only an existing deterministic fallback with `INVALID_MODEL_OUTPUT`; with
no fallback return `UNSUPPORTED_GOAL` and no plan. Model-unavailable and
malformed-output paths likewise use fallback statuses only when a plan exists.
The live matrix is `docs/evidence/never-fabricate-matrix.md`; its correction
passed 17 focused planner tests and the 361-test hermetic lane.

Submission evidence must follow D059 and D060. Fill
`docs/evidence/novice-vscode-study.md` live; never invent participant rows,
drop failures, or make a participant-value claim below two completed sessions.
Use `docs/submission/demo-video-script.md` for the 4:45 recording. Open Folder,
Ask/Open Terminal, and the refusal clip are protected segments; if product code
changes behavior after recording, rerun the affected tests and rerecord that
clip. Sending invitations and uploading video are external actions and must not
be claimed from repository edits alone.

Real VS Code perception is intentionally narrow for each validated workflow.
`perception_walker_for("code.exe", recipe_intent)` selects the reviewed walker
for that recipe. Open Folder uses `uia.iter_vscode_elements`, which since D069
uses the **bounded-descendants** strategy: a `Code.exe`-bounded Button walk
filtered by NORMALISED name against the `Open Folder` variants, capped at
`DEFAULT_DESCENDANT_LIMIT`. It never performs the generic full Electron
descendant walk. It previously used a provider-side exact query, which on
VS Code 1.134.0 returns a dead COM pointer for this target while the Button
walk reads it cleanly — so the workflow had silently fallen back to OCR for its
grounding. Matching is normalised because VS Code prefixes a private-use
Codicon to the accessible name; the glyph is never written into a recipe, since
a specific codepoint is version-sensitive. A clean absence still returns an
empty successful observation so executable-bounded OCR can escalate, but a
genuine provider fault now raises `ProviderQueryFault` instead of
masquerading as an empty screen. OCR
same-line reassembly is required because Windows reads `Open` and `Folder...`
as separate words; it does not lower the 95 grounding floor. Keep this restriction
aligned with the trusted VS Code pack; broaden it only when a new
reviewed VS Code recipe needs another target. Progress stages must be written
before potentially blocking calls so health logs do not misidentify a blocked
walk as a focus stall.

Open Terminal uses `uia.iter_vscode_terminal_elements`, a `Code.exe`-bounded
Button walk filtered to exact `Toggle Panel (Ctrl+J)` and `Terminal Section`
names. Neither exposes a stable AutomationId. Never invent one, persist these
name-only controls, or claim focus-based wrong-action naming for this workflow:
promotion and wrong-action feedback intentionally fail closed without an ID.
Keep `accept_if_already_present` and `timeout_from_hint` on this recipe. The
first prevents an already-satisfied goal from receiving a shortcut that closes
it; the second bounds a no-op shortcut that provides no observable action
event. Both options are schema-checked and covered by injected-clock tests.

Executable recipe targets are identity-bounded. `app_info_for_window()` may
accept `expected_app_id`; `perception_hwnd_source_for()` supplies the same
executable filter to the worker and focus guard; and the VS Code walker accepts
only `Code.exe`. Never weaken this to title-only matching: titles are free text
and collide with browser tabs and terminals. Missing trusted identity must fail
before overlay creation.

Repository stabilization is green through the bounded hang audit. The
hermetic lane passed **341 tests twice consecutively**; interactive passed 53;
pytest pixel passed 3; standalone pixel harnesses passed 16/16 and 8/8; and
the isolated hung modules passed 4, 2, and 7 tests. Keep
whole-file concern commits, preserve raw hang dumps only under ignored
`.artifacts/hang-audit/`, and record sanitized reachability findings in
`DECISIONS.md`. Test-lane ownership lives centrally in `tests/conftest.py`.
Do not run two desktop/UIA sessions at once or run a hung-window lane beside
anything else.

Release policy is locked: feature development ends 30 August at 20:00 IST;
31 August permits fresh-clone validation and release-blocking fixes only; code
freezes at 31 August end-of-day; 1 September is upload/paste/verify only; and
2 September is an emergency link/upload/form buffer with no code changes.

After every finalized slice, update `DECISIONS.md`, `FLOW.md`, and this file,
independently review the documentation against the implementation, run the
relevant regression tests, refresh Graphify when available, and commit the
slice before starting the next mutation.

The control surface is a vertical middle-right rail, not a horizontal toolbar.
Compact geometry is 148×192px with Stop/Pause/Ask stacked vertically and
status below. Ask preserves the right edge and centre, expands left to
520×260px, and adds a 372px prompt column containing `Type your goal:` and a
multiline scrollable EDIT. Never create panel children outside the current
parent rectangle: Win32 clips them even though their HWNDs exist. The prompt
must not overlap the right safety rail; closing/submitting restores compact
geometry. Bar/runtime integration is 32 passing tests.

Real VS Code open-folder acceptance passed 3 of 3 consecutive successful
runs; that workflow gate is closed. The expanded Ask prompt has been visually
validated on a real desktop: its label, multiline input, Submit, status,
Stop, and Pause are visible without clipping or overlap. The user then entered
and submitted the goal; the shared planner launched a fresh trusted VS Code
tour and it reached `Tour complete.` The Ask behavioral gate is closed. Keep
the `Ask received` console acknowledgement before nested `run_tour()` because
the nested control-bar session may remain alive until its timeout.

Real VS Code open-terminal acceptance also passed 3 of 3 consecutive clean
runs from a confirmed hidden-panel baseline. The evidence is fresh live
grounding plus an observed `Terminal Section` transition on each run; it is not
a learned-observation reuse claim because the controls have empty IDs.
Post-review regression is 50 focused, 355 hermetic, and 55 interactive tests.
The corrected desktop path passed one already-present run with no hint plus
3/3 consecutive hidden-to-visible transitions.

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

```powershell
# Fast, hermetic lane: no real desktop, pixels, or deliberately hung windows.
py -3.12 -m pytest tests -m "not interactive and not pixel and not hung" `
  --basetemp=.tmp\pytest-hermetic -p no:cacheprovider

# Interactive Win32/UIA lane: run on a normal unlocked Windows desktop.
py -3.12 -m pytest tests -m interactive `
  --basetemp=.tmp\pytest-interactive -p no:cacheprovider

# Pixel lane: do not cover or move the test windows while this runs.
py -3.12 -m pytest tests -m pixel `
  --basetemp=.tmp\pytest-pixel -p no:cacheprovider
py -3.12 -m tests.test_overlay
py -3.12 -m tests.test_end_to_end

# Hung-window lane: each command runs ALONE, never beside another test session.
py -3.12 -m pytest tests\test_hung_window.py `
  --basetemp=.tmp\pytest-hung-window -p no:cacheprovider -o faulthandler_timeout=60
py -3.12 -m pytest tests\test_perception_service_hung.py `
  --basetemp=.tmp\pytest-hung-service -p no:cacheprovider -o faulthandler_timeout=60
py -3.12 -m pytest tests\test_run_threaded.py `
  --basetemp=.tmp\pytest-hung-runtime -p no:cacheprovider -o faulthandler_timeout=60
```

`pytest` does not collect the two standalone pixel harnesses above — they keep their own
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
                     # which control has focus right now (focus.py);
                     # tier 2: mss window capture/diffing (capture.py), Windows.Media.Ocr
                     # (ocr.py), cadence and caps (tier2.py), Chromium warm-up
                     # suppressing tier 2 while a cold accessibility tree populates
                     # (warmup.py) — built and wired.
                     # Tier 3 (VLM) not yet built
  reasoning/          # observe-act-verify state machine (loop.py), grounding ladder +
                     # promotion (grounding.py), verification, staleness ladder
                     # (staleness.py), recipes, overlay renderer
  memory/             # SQLite knowledge base of learned observations (store.py); see "Stored data" above
  inference/           # shared bounded Ollama transport + screen-hint decisions
  evaluation/          # semantic dataset, UIA fixture, read-only three-lane gate
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

## Open Track submission evidence status

- Release recertification and the never-fabricate matrix are complete.
- The novice VS Code study protocol is locked in
  `docs/evidence/novice-vscode-study.md`: symmetric 120-second attempts,
  first-action and world-state completion timing, wrong turns, help requests,
  and confidence before baseline/after guidance.
- Three participants are preferred; two require explicit `n=2` disclosure;
  fewer than two permits engineering evidence only and no participant-value
  claim.
- Recruitment is deliberately deferred until eligible participant contacts or
  an authorized communication channel are available. Do not claim recruitment
  or confirmation without real external evidence, and never commit participant
  identities or contact details.
- The demo remains the locked 4:45 sequence. It must not claim VS Code
  AutomationId-based wrong-action recovery.

## Model-durability outcomes (complete)

D068 and D069 close the two feasibility spikes and reset the next milestone.

**D070 — keep runtime memory, curated knowledge, and execution authority
separate.** Screen-derived observations remain in erasable `kb.sqlite`; future
curated knowledge is local-only in a separate `knowledge.sqlite`; and only a
schema-valid JSON artifact explicitly named by a manifest can authorize a
workflow. Drafts stay quarantined outside trusted roots. Adoption is always
human-gated and ordered quarantine -> isolated no-input-synthesis acceptance ->
content-addressed install -> manifest swap; table design remains deferred until
the declarative compiler stabilizes the shapes. See D070 for withdrawal,
version scope, evidence, digest, cache, and fail-closed requirements.

**D068 — the local model cannot change which recipe executes.** Measured: zero
of 60 case-runs changed the executable recipe, with exactly one model request
per case and the deterministic/policy views derived purely from that same
sample. The model varies status, named intent, confidence, explanation, and
latency, and nothing else. Do not present raw semantic accuracy as workflow
capability, and do not use it as a model replacement criterion. Model swapping
is deferred: a smaller model currently offers only latency and RAM gains.

**D069 — workflow #3 is feasible with what already exists.** Open Extensions is
selected (`strategy-1` on `Extensions (Ctrl+Shift+X)`, `element_appears` on
`Installed Section`, persistent, empty AutomationId). Command Palette is
rejected on measured grounds. No new verification kind, no new selector
strategy.

**Presence rule — this supersedes any pointer-based check.** `FindFirst`
returning a non-`None` object is not evidence of presence:

| `FindFirst` | property read | meaning |
|---|---|---|
| object | succeeds | present |
| object | `NULL COM pointer access` | absent |
| object | any other COM/read failure | perception fault |

`provider_exact()` owns this classification, and every provider-side exact query
must route through it. A non-presence property-read failure raises
`ProviderQueryFault` instead of being collapsed into an empty successful
observation. Verification never treats pointer existence as evidence,
`element_appears` and `element_disappears` included. The earlier "shell chrome
versus webview" explanation is **retracted** — it was wrong.

**Open Folder's tier-1 perception was restored and revalidated.** The workflow
was migrated to `bounded_descendants()` with `EXACTLY_ONE` cardinality and
normalised trusted-name matching. Gate 1 passed 5/5; gate 2 passed 3/3 with
in-tour `source=uia` grounding and zero OCR. Never write the observed leading
Codicon glyph into a recipe — a private-use codepoint is version-sensitive.
Migration gates must assert UIA provenance rather than mere completion, because
fallback OCR can preserve the outcome while the preferred tier is dark.

**Never promote positional AutomationIds.** `list_id_<number>_<number>` encodes
a list index, not a control. They are the only non-empty ids VS Code exposes,
and `promote()` would happily persist one.

D063 is now built: both inference paths use the shared adapter, parsers accept
only canonical bounded fields, planner null is an explicit abstention, and
`resolve_model_decision()` is the single production/evaluation authority
policy. Never bypass that function in an evaluation runner.

D064 is built: a 30-case versioned semantic dataset, provenance-tagged
Synthetic Export UIA fixture, and three-lane read-only gate now exist. D066
freezes owner-reviewed version 1.0.0; pre-freeze draft reports remain diagnostic
and must not be called the incumbent baseline. The first complete draft passed all
hard gates at 86.7% overall raw semantic accuracy and 100% on exact supported
goals; D058 denied authority to all four raw over-commitments.

Any change to a model name or digest, Ollama request options, prompt, JSON
schema, parser, adapter, planner inference, hint inference, or authority policy
requires the complete model-durability gate. Run it with `--interactive` and
without `--draft`; a non-interactive skip cannot close the milestone. `--draft`
is reserved for an explicitly unfrozen dataset revision and cannot produce a
promotable report:

```powershell
py -3.12 -m ghostcursor.evaluation.model_gate `
  --model qwen3:4b-instruct `
  --endpoint http://127.0.0.1:11434 `
  --unavailable-endpoint http://127.0.0.1:1 `
  --interactive
```

The evaluation package is read-only by construction. Do not import
`ghostcursor.run`, `ghostcursor.reasoning.loop`, overlay creation, or any input
synthesis API into it. Full reports are ignored under
`.artifacts/model-evaluation`; commit only a reviewed summary. Final acceptance
requires two consecutive non-draft full passes; every failure resets the count
to zero and must be preserved and classified first.

D065 fixed evidence promotion: timestamped JSON remains ignored, while
`docs/evidence/model-durability-draft.md` is the concise, reviewable diagnostic
summary. Its pre-freeze numbers remain diagnostic and are not the incumbent
baseline.

D066 froze owner-reviewed dataset version 1.0.0. Its misspelling asymmetry is
an observed anchor-rule result, not fuzzy matching: only `intergrated` preserves
the required `open + terminal + VS Code` anchors. The trusted baseline runs used
non-draft mode after that freeze.

D067 closes that count: two consecutive complete post-freeze interactive gates
passed with identical 26/30 raw semantic accuracy, 6/6 exact supported, zero
unsupported launches, and unchanged no-action evidence. The incumbent is
`qwen3:4b-instruct` at manifest digest
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
`docs/evidence/model-durability-baseline.md` is the committed baseline; future
model/request/prompt/schema/parser changes compare against it and retain this
digest as the rollback target.

## Forward work (not started)

- Build recipe schema v2 and the declarative workflow compiler around the two
  measured selector strategies: `provider_exact` and `bounded_descendants`.
  Recipes declare strategy; the compiler never infers it.
- Make intent registration declarative. `registry()` is still a hardcoded Python
  dictionary, so Open Extensions cannot be a data-only workflow while it stays
  one.
- Migrate Open Folder and Open Terminal to schema v2, then add Open Extensions
  through manifest and recipe data with no workflow-specific change under
  `ghostcursor/**/*.py`.
- Budget roughly nine human-driven real-desktop acceptance runs: 3/3 for each
  migrated workflow and 3/3 for Open Extensions.

`post-submission/model-durability` is frozen by the `durability-final` tag on
this corrective commit. All schema-v2 design and implementation belongs only to
`feature/declarative-workflow-compiler`; intentional work there may now diverge
from durability. Never merge the durability branch into the certified
`submission/open-track` branch.
