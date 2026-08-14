# DECISIONS.md

Log of meaningful decisions made while building the Ghost Cursor project, and the
reasoning behind them. Append new entries at the bottom, newest last. Each entry:
what was decided, what alternatives existed, why this one won.

---

## D001 — Project identity: Ghost Cursor (Phase 1 of AIOS)
**Decision:** The first buildable thing is "Ghost Cursor" — a real-time on-screen
guide agent — not the full "AI Operating System" vision described in `My idea.docx`.
**Alternatives considered:** Jumping straight to the broader AIOS vision (cross-app
memory, adaptive interfaces, company-brain integration).
**Why:** The full vision has no near-term concrete artifact. Ghost Cursor is
Stage 1 ("Teach") of the roadmap in `My idea.docx` and matches the existing,
detailed build doc already in `D:\tracker\docs\ghostcursor\build-the-ghost-cursor-mvp-...docx`.
Every later AIOS stage (Onboard, Support, Collaborate, Operate) is a superset of
this perception+overlay+reasoning loop, so building it first isn't a detour.

## D002 — Platform: Windows-first, not cross-platform
**Decision:** Target Windows only for v1. Use win32 APIs (win32gui/win32con/win32api,
already installed) for the overlay, and Windows UI Automation (via `pywinauto`) for
the accessibility tree.
**Alternatives considered:** Rust+Tauri cross-platform from day one; porting OpenClicky
(Swift, macOS-only).
**Why:** User's dev machine is Windows. OpenClicky is a strong reference architecture
but is macOS/Swift-native — not directly portable. Building Windows-native first
means every early bug (overlay click-through, UIA quirks) is solved on the actual
target platform instead of guessed at cross-platform abstractions. Tauri packaging
is deferred to a later phase (gc.16–18 in the build doc) — it's a distribution
decision, not a prerequisite for proving perception+overlay+reasoning works.

## D003 — MVP scope: local overlay + bridge, no AI yet
**Decision:** First working milestone is a transparent, click-through Win32 overlay
window that can draw a static hint ring at a hardcoded coordinate — no LLM, no
screenshot pipeline, no reasoning loop yet.
**Alternatives considered:** Building the full tag-based pointing loop
(screenshot → LLM → `[POINT:x,y]` → overlay) end-to-end first.
**Why:** This mirrors both OpenClicky's own retrospective advice ("get the overlay
+ bridge working with curl before any model is involved — it proves the hardest
platform-specific UI problem, click-through without stealing real clicks, before
any model is involved") and the build doc's own "Beginner Project" tier
(Static Hint Overlay in Notepad, ~4 hrs). De-risk the platform-specific UI plumbing
before spending time on the AI loop.

## D004 — Language/stack for the core agent: Python
**Decision:** Perception, overlay, reasoning loop, and memory all in Python
(pywinauto, mss, win32gui/GDI, SQLite, Ollama client).
**Alternatives considered:** Native C++/C# for the overlay for lower latency; Rust.
**Why:** Matches the build doc's stack exactly, and matches what's already
installed (`pywin32`, `numpy`, `ollama` present; `pywinauto`/`mss` to be installed).
Python is fast enough for this MVP's latency budget (sub-second hot path via a
small local model + streaming) and keeps perception/reasoning/overlay in one
language during the exploratory phase. Packaging with Tauri later can wrap this,
or the core can be rewritten in Rust once the architecture is proven — that's an
explicit, deferred decision, not a default.

## D005 — Perception: tiered, cheapest-first (UIA → OCR → VLM)
**Decision:** Try Windows UI Automation (`pywinauto`) first for any target window.
Fall back to raw screen capture (`mss`) + OCR (`PaddleOCR`) for text-only needs.
Fall back further to a VLM pointing model (MolmoPoint-style) only when nothing
structured exists.
**Alternatives considered:** Always using a VLM/vision model on every frame
(what a naive "screenshot → GPT-4V" implementation would do).
**Why:** UIA queries are near-free and give exact coordinates when available.
VLM calls are the slowest and most expensive tier and should be the last resort —
this is the same lesson OpenClicky's own architecture review reached (two-tier
pointing: cheap tag-based guess embedded in the normal LLM response, escalate to
a dedicated Computer-Use-style call only when precision actually matters).

## D006 — Overlay never touches the real OS cursor
**Decision:** The overlay only draws a visual hint (ring/arrow/tooltip) at a
coordinate. It never calls `SendInput`/`mouse_event` to move the real system
cursor or synthesize a click. Any future real-mouse-takeover capability must be
a separate, explicitly opt-in code path.
**Alternatives considered:** Using PyAutoGUI to actually move the cursor for a
more "magical" demo.
**Why:** This is flagged in the build doc as "the single most important safety
design decision in the whole project," and OpenClicky's own retrospective
independently arrived at the same rule after their real-cursor-warping transport
became tech debt they were stuck untangling. Visual-only is reversible and low-risk;
real takeover is not.

## D007 — Docs from `D:\tracker\docs` are the primary reference corpus
**Decision:** Before building any subsystem, check `D:\tracker\docs\ghostcursor\`
(and `aios\`, `agents\`, `agentinfra\` for later phases) for an existing note on
the topic, and tag/cite it in `DECISIONS.md`/`FLOW.md` rather than re-deriving
from scratch.
**Why:** User explicitly asked to be able to read from that folder to build
understanding alongside the code. These docs already encode specific tradeoffs
(e.g. WS_EX_LAYERED vs WS_EX_TRANSPARENT, fake-cursor-vs-takeover, Tauri vs
Electron) that would otherwise be silently re-decided.

## D008 — Tracking docs: DECISIONS.md + FLOW.md, updated as we build
**Decision:** Maintain `DECISIONS.md` (why) and `FLOW.md` (how execution actually
travels between files/functions) as living documents, updated with every
meaningful change — not written once and abandoned.
**Why:** User explicitly wants to understand the entire codebase and reasoning
as it's built, not just receive finished code.

## D009 — All drawing happens inside WM_PAINT; callers never touch a DC
**Decision:** `overlay/window.py` owns its paint cycle. `_wnd_proc` handles
`WM_PAINT` by filling the entire client area with the colorkey colour and then
drawing the current hint on top; `WM_ERASEBKGND` returns 1 so Windows doesn't
erase separately. Callers never draw — they call `set_hint()`/`clear_hint()`,
which update module state and invalidate the window.

**Bug this fixes (the one that whited out the user's screen).** The first
version drew with `GetDC(hwnd)` from the polling loop, *outside* any paint
cycle, and relied on the window class's background brush to erase. That left
the window's surface never authoritatively initialised, so it contained
uninitialised garbage. Because that garbage was not the colorkey colour, none
of it was made transparent — the overlay rendered as an opaque wash covering
the whole screen. Measured directly: a full-screen grab with the overlay up
was 64% white / 28% black and **0% magenta**, i.e. the colorkey was never
painted anywhere. Ring pixels from *previous runs* were still present in the
surface (cyan found at y=1064 when the only hint drawn was at y≈400), proving
the surface was accumulating rather than being cleared.

**Alternatives considered:** keeping the loop-draws-directly design and adding
an explicit erase before each draw. Rejected — it keeps the window's contents
dependent on the caller's call order, and any missed frame or external repaint
(another window moving over the overlay) reintroduces garbage. Owning
`WM_PAINT` makes the surface a pure function of the current hint state.

**Related safety note:** because the overlay is click-through and never takes
focus, an opaque bug like this cannot be dismissed by clicking it — this is
precisely how a rendering bug becomes "I can't see or do anything." Hence
D011's kill switch.

## D010 — One coordinate space, declared before anything can flip it
**Decision:** `overlay/dpi.py` declares DPI awareness at *import* time and is
imported by `overlay/window.py`, so awareness is set before any window is
created. All geometry — window rects, UIA rects, hint coordinates, screen
captures — then lives in one consistent space, obtained via
`dpi.virtual_screen_rect()` / `dpi.capture_region()`.

**Bug this fixes.** With 125% Windows scaling this machine reports two screen
sizes, and *which one you get changes during the process's lifetime*:

    metrics at process start      -> 1536 x 864     (DPI-unaware)
    after SetProcessDPIAware()    -> 1920 x 1080    (DPI-aware)

`python-mss` calls `SetProcessDPIAware()` itself on initialisation. So merely
taking a screenshot silently changed what `GetSystemMetrics` returned for the
rest of the run. A window created before the first screenshot was sized
1536x864 and covered only **64%** of the screen; the identical call after a
screenshot covered 100%. Same code, different result, depending on whether
anything had grabbed a frame yet.

**Also note:** `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` returns
**0 (failure)** on this machine even as the very first call in the process,
while the older `SetProcessDPIAware()` returns 1 and works. Both are tried,
newest first. And awareness locks permanently the moment any DPI-dependent API
is called — so querying metrics *before* declaring awareness silently forfeits
the choice. That is why this lives at module import and not in `main()`.

**Correction to an earlier entry:** a previous version of this file claimed
UIA returns a degenerate `(0,0,0,0)` rect for real windows and added a raw
`win32gui.EnumWindows` fallback for it. That reading was wrong — it was this
same DPI/awareness inconsistency. With awareness declared first, UIA returns
correct rects (`(160,160,1009,945)` for Notepad). `_raw_window_rect()` is kept
as a genuine defensive fallback (some apps really do expose no usable UIA
geometry) but it is *not* load-bearing, and the original justification for it
was a misdiagnosis.

## D011 — The overlay must always be killable without focus
**Decision:** `run.py` polls `GetAsyncKeyState(VK_ESCAPE)` each tick and exits,
stops on its own after `--seconds` (default 60), and tears the window down in a
`finally` block. `overlay.destroy_overlay_window()` swallows errors so teardown
can never itself strand the window.

**Why:** the overlay is full-screen, topmost, click-through and never takes
focus, so it has no title bar, no taskbar entry and cannot receive a click or a
normal key event. If it renders wrong, the user has no in-band way to close it —
which is exactly what happened during this build (D009). A polled ESC works from
any application precisely *because* it doesn't require focus, and the timeout
means even a hung loop releases the screen.

## D012 — Verify with measurement, not by asking a human to look
**Decision:** correctness is checked by `tests/test_overlay.py` (14 checks) and
`tests/test_end_to_end.py` (4 checks), which assert against pixels and Win32
state rather than a person's judgement:
- click-through is proven with `WindowFromPoint`, which performs real
  hit-testing — the point must resolve to the window *underneath* the overlay;
- transparency is proven against a controlled solid-colour backdrop
  (`tests/backdrop.py`) rather than the live desktop, so unrelated screen
  activity can't produce false results;
- hint placement is proven by locating the ring's pixels and comparing its
  centroid to the requested coordinate.

**Why:** every wrong turn in this milestone came from a bad oracle. Screenshots
taken from a *separate* PowerShell process appeared blank/stale, which produced
the earlier (now deleted) conclusion that "this sandbox can't screenshot the
desktop" — a build-environment excuse that was simply false. The real problem
was that the other process had different DPI awareness, so it captured a
region that didn't correspond to the desktop. Capturing in-process, against a
known backdrop, with the coordinate space pinned (D010), turns "does it look
right" into a number. That is also what caught the stale-ring bug, which is
invisible to a glance at a static screenshot.

**Result:** 18/18 checks pass, and the ring was additionally confirmed on a
real Notepad window — 440 ring pixels, 49x49 diameter, centroid within 1px of
the requested coordinate.

## D013 — The grounding ladder is a promotion mechanism, not just a fallback chain
**Decision:** `grounding.ground()` tries rung 1 (confirmed `automation_id`),
then rung 2 (control_type + exact name), then rung 3 (fuzzy name), and a
successful match at rung 2 or 3 is *promoted* — written back onto the step as
a confirmed `automation_id` — rather than just used once and discarded.
Locale gates rungs 2-3 (text matchers) only; rung 1 is never filtered by
locale.
**Alternatives considered:** Treating the ladder as a pure fallback (try each
rung fresh every time, keep nothing); requiring recipe authors to supply an
`automation_id` up front.
**Why:** An `automation_id` cannot come from documentation or a recipe
author's inspection session — it's an implementation detail of the live app,
and recipes are meant to be hand-authored from a description of what the UI
looks like, not from a debugger. So the *first successful grounding* is the
only place a trustworthy `automation_id` can come from, and recording it
there means every later run of the same recipe against the same app can
resolve at rung 1 — fast and language-independent — even though the first
run had to fall back to fuzzy text matching. Locale must gate rungs 2-3
because displayed text changes with the UI's language, but rung 1 is an
opaque identifier the app itself assigns and is stable across translations
by construction; filtering it by locale would silently break the exact
mechanism promotion exists to enable. Persisting the promotion across
process runs (rather than just within one `GuidedTour`) is knowledge-base
territory and is deliberately out of scope for this milestone (see FLOW.md).

**Superseded in part:** the "out of scope for this milestone" sentence above
is no longer current — D015, D016 and D017 build exactly that: selection
between stored observations across versions (D015), a durable cross-run
step key (D016), and the persisted store itself (D017). The rest of this
entry (rungs, locale gating rung 1 never rungs 2-3) still holds.

## D014 — Verification checks world state, never the method used to get there
**Decision:** `verification.verify(rule, before, after)` inspects the live
UIA snapshot after the user's action and compares it against the rule's
predicted post-condition. It never inspects *how* the user got there — no
keystroke log, no click trace, no check that a specific menu was opened.
**Alternatives considered:** Recording the exact interaction path implied by
`instruction_text` (e.g. "open File > Save") and verifying the user followed
those literal steps.
**Why:** A step can say "click File > Export" and be legitimately satisfied
by the user pressing Ctrl+Shift+E instead — the goal is the exported file
existing / the dialog appearing, not the sequence of clicks that produced it.
Grading the route rather than the outcome makes the tour wrong exactly when
the user is more efficient than the recipe author anticipated, which is the
opposite of what a teaching tool should do. This mirrors OSWorld's
execution-based grading (inspect real state, don't grade a transcript) and is
the same reasoning D012 already applied to testing the overlay itself:
measure what actually happened, not the expected sequence of calls that was
supposed to produce it.

## D015 — Observation selection: exact, else nearest lower, else unknown — never newer
**Decision:** `grounding.select_observations()` implements spec §9's ladder: an
exact `app_version` match if one exists; otherwise the observations from the
nearest *lower* verified version; otherwise observations with no parseable
version at all (unknown/global). A version newer than what's running is never
selected. Non-exact matches are then cross-checked in `ground()` — the live
element's `control_type` must equal the observation's, or it is rejected and
grounding falls through to rung 2 (name matching).
**Alternatives considered:** Requiring strict version equality before an
`automation_id` can be trusted at all.
**Why:** AutomationIds survive version changes far more often than they
break — they're implementation details assigned once and rarely renumbered
across patch releases. Strict equality would discard every learned id on
each patch bump and force re-learning from scratch on every update, which
defeats the entire point of promotion (D013). "Nearest lower, never newer"
also encodes something version numbers actually mean here: an id observed
on 3.0 says nothing reliable about what 2.0 displayed, but an id observed on
2.0 is a reasonable guess for 2.1 or 3.0 until proven otherwise. The
`control_type` cross-check is what makes reusing a non-exact match safe
rather than reckless: if the id has been reassigned to a different kind of
control, the cross-check catches that and the ladder falls through instead
of pointing at the wrong thing. This asymmetry is deliberate — failing to
ground is visible and recoverable (the tour can fall back to rung 2/3, or
report nothing found), whereas mis-grounding teaches the user something
false with no signal that anything went wrong. Given that asymmetry, it is
correct to bias toward reuse (with a check) rather than toward safety by
exact match alone.

## D016 — Step identity: a durable key over the claimed descriptor, not position
**Decision:** `identity.step_key(intent, step)` hashes the recipe's intent
(as namespace) plus the step's *claimed* `name`, `ocr_text`, and
`visual_description`. It does not use `(intent, step_index)`, and it
excludes `name_synonyms`.
**Alternatives considered:** Keying persisted observations by
`(intent, step_index)`, which is simpler and was the first thing tried.
**Why:** `(intent, step_index)` is unusable in practice — inserting a step
anywhere before the end of a recipe silently shifts every later index, so
observations learned for "click Export" would silently re-attach to
whatever instruction now occupies that slot after an edit. Hashing the
claimed descriptor instead ties learned data to *what the step describes*,
which is stable under insertion and reordering. `name_synonyms` is
deliberately excluded from the hash: synonyms are alternate spellings of the
same target ("Export" vs "Save As"), and adding one is an editorial
improvement, not a change of target — it must not discard what the step has
already learned. `visual_description` is deliberately included: it is what
separates two steps that share a name but differ in location ("Delete in
the toolbar" vs. "Delete in the dialog") — exactly the collision that would
otherwise let one step's observations mis-ground the other. The consequence
is by design, not a gap: editing `name`, `ocr_text`, or `visual_description`
orphans that step's previously learned observations, because the step now
describes a different target and inherited evidence about the old one would
be wrong.

## D017 — The persisted store: local, erasable, keyed for idempotent promotion
**Decision:** `memory/store.py`'s `ObservationStore` is a SQLite database at
`%LOCALAPPDATA%\GhostCursor\kb.sqlite` (overridable via `GHOSTCURSOR_KB_PATH`,
which is what lets tests and the two-process end-to-end proof share a
scratch database without touching the real one). It is the first thing in
the system to write screen-derived data to disk: application identity
(`app_id`, `app_version`) and the names/AutomationIds of UI elements read
from the user's screen. The table's primary key is
`(step_key, app_id, app_version, automation_id)`.
**Alternatives considered:** An append-only log of every observation ever
seen, keeping full history.
**Why:** Local-only, no telemetry, no network, no cloud sync — the §2
invariant governs data *leaving* the machine and this doesn't touch it, but
the locality is deliberate and worth stating plainly rather than leaving
implicit. Deleting the file fully erases the knowledge base; the system
simply re-learns from scratch on the next run, the same as a first run ever
has. The composite primary key is what makes promotion idempotent:
re-observing the same id for the same step, app and version updates one row
(merging locales, bumping `ok_count`) instead of appending a duplicate every
tick — this is what closes the unbounded-growth problem parked in the
previous milestone, without needing a separate cleanup pass.

## D018 — A green suite is not evidence; mutation-test the properties that matter
**Decision:** for any property whose failure would be silent and expensive —
identity keys, safety guards, round trips — do not accept "the tests pass" as
proof. Deliberately break the implementation, run the suite against the broken
copy, and confirm it notices. Only then is the property actually protected.

**Why this is a decision and not a platitude.** It was learned twice on this
project, both times on code that looked finished:

- `step_key` (D016) shipped with a green suite through two review rounds. Two
  mutations survived it: dropping `ocr_text` from the key, and replacing the
  `\x1f` field separator with a space. Either would silently merge two
  different steps' learned observations, so a hint learned for one instruction
  would be reused for another — the exact mis-grounding this project exists to
  avoid. Neither the implementer nor two reviewers caught it; a six-mutation
  matrix did, in about a minute.
- Earlier, a test named `test_field_separator_distribution_does_not_collide`
  asserted that two inputs produce the *same* key. The name claimed one thing,
  the assertion did the opposite, and it passed.

**The pattern behind both:** a test can describe correct behaviour without
being able to detect incorrect behaviour. That gap is invisible in review,
because a reviewer reads the test and agrees with what it says. Mutation
testing is the cheapest way to close it, and it is worth doing at the point a
property is first introduced rather than after something has gone wrong.

**How it is applied here:** every safety-critical property added in the
persistence milestone was mutation-verified before its task was accepted — the
`control_type` cross-check, the never-use-newer-observations rule, the store's
idempotent primary key, the locale merge, and both halves of the
persist/hydrate round trip. Each was confirmed to FAIL the suite when broken.

**Cost:** a few minutes per property, and the discipline to break your own code
on purpose before believing it works.
