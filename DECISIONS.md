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
**Decision:** correctness is checked by `tests/test_overlay.py` and
`tests/test_end_to_end.py` — 14 and 4 checks when this was written, more since,
as each new visual state earns one — which assert against pixels and Win32
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

## D019 — Which perception snapshots share an instant, and which must not
**Decision:** `OBSERVING` and `DECIDING` share one UI tree walk;
`AWAITING_USER_ACTION` always takes its own, fresh.

**Why it matters, and why it is easy to break.** These two look like the same
kind of call, and merging all three "for consistency" is a natural-looking
refactor that would silently destroy verification:

- `OBSERVING` → `DECIDING` describe **one instant**: "here is the screen, now
  decide what to point at." Reading the tree twice was not merely slower, it
  was slightly wrong — grounding could act on a state the snapshot never saw.
- `AWAITING_USER_ACTION` must describe a **later** instant. Its entire job is
  to ask whether the user has acted *since* the hint was drawn. Sharing the
  earlier snapshot there would compare a state against itself, so verification
  could never succeed and every tour would stall on its first step.

`tests/test_tick_latency.py::test_observing_and_deciding_share_one_tree_walk`
pins the sharing; the verification tests cover the separation.

## D020 — A standing ceiling on tick latency, because the escapability rule has no other enforcement
**Decision:** no code path on the tick path may block longer than
`TICK_CEILING_S` (0.5s), enforced by `tests/test_tick_latency.py`.

**Why a standing test rather than another point fix.** The overlay is
full-screen, topmost, click-through, has no title bar and never takes focus,
so ESC and `--seconds` are the only ways out — and ESC is polled *between*
ticks. A blocking tick is therefore time the user cannot escape a window
covering their screen. That invariant has now been broken twice by unbounded
calls, each found only after the fact:

- drawing outside `WM_PAINT` left the surface uninitialised, painting an
  opaque wash over the desktop (D009);
- three `wait("exists", timeout=3)` calls per tick meant an absent target —
  the user simply alt-tabbed — blocked a tick for **9.1 seconds** measured,
  every tick, with the overlay up.

Two occurrences is a pattern, not coincidence: nothing enforced the rule
structurally. The ceiling does. A future OCR fallback, VLM call, or a
knowledge-base lookup that reaches the network now trips a test instead of
shipping silently.

**Why not a runtime watchdog.** A watchdog thread cannot rescue a blocked
tick, and this was verified rather than assumed: `DestroyWindow` from a
non-owning thread fails with `Access is denied` and the window survives, and
`PostMessage` needs the main thread's message pump — precisely what a blocked
tick is not running. The only real runtime fix is to keep perception off the
UI thread so it always pumps and polls ESC. That is a genuine change and is
deliberately not smuggled in here; until then the ceiling is the guard.

**Measured effect of the fix this decision came from:**

```
absent-window tick   9,124 ms  ->  0.39 ms
one tree walk           67.6 ms ->  26.0 ms   (dropped a redundant wait)
observe -> hint          2 walks ->  1 walk
```

---

## D021 — Perception runs on a worker thread, not the UI thread

**Decision.** The UI-tree walk moves onto a dedicated worker thread that owns
its own COM apartment. The UI thread reads the worker's latest result without
ever blocking on it, and keeps pumping messages and polling ESC no matter how
slow perception becomes.

**What forced it.** D020 capped the tick at 0.5 s and enforced it with a test,
but that test uses an *absent* window. A window whose owner has stopped
pumping messages — an ordinary "Not Responding" app — is a different failure
and the ceiling test cannot see it. Measured on this machine:

```
windows_matching   1.22 ms   -> 1 window     the cheap existence check SEES it
iter_elements     41,270 ms  -> 0 elements   81x the 0.5s tick ceiling
repeat walks      10,100 ms  each            bounded, self-healing
```

41 seconds is 41 seconds during which ESC — polled *between* ticks — does not
work, on a full-screen, topmost, click-through window with no title bar. This
is more likely than the failure D020 already fixed: apps hang far more often
than they vanish mid-tick. UIA exposes no timeout to tune, so no amount of
care at the call site helps.

**Why not a watchdog.** Verified, not assumed: `DestroyWindow` from a
non-owning thread returns `Access is denied` and the window survives;
`PostMessage` needs the message pump that a blocked tick is not running. A
watchdog cannot clear the overlay while the UI thread is stuck. The only real
fix is to stop blocking the UI thread — which D020 named as the eventual
answer and deliberately did not smuggle in at the time.

**COM ownership.** The worker calls `CoInitializeEx` and owns its `Desktop()`
entirely. UIA objects are apartment-bound, and passing one across threads
produces confusing intermittent failures rather than a clean error. Only
frozen dataclasses of primitives cross the boundary — `Element`, `Snapshot`,
and the timestamp. No COM object ever does. The perception layer already
normalised to exactly those types, which is what made this boundary cheap.

**Proof it holds.** `tests/test_run_threaded.py` drives the real `run_tour`
against a real hung window. Putting a UIA walk back on the UI thread fails it
with `ESC was only polled 7 times before run_tour returned`, and the run takes
95.6 s instead of 16 s.

---

## D022 — A single timestamped slot, not a queue and not futures

**Decision.** The worker publishes each observation by *overwriting* one slot.
The slot holds one timestamped `Observation` and no history.

**Why not a queue.** A queue drained to "take the newest and discard the rest"
is a depth-1 buffer with extra ceremony: there is no depth to tune, no explicit
discard step to get wrong, and overwrite *is* the discard.

**Why not futures.** A future answers "which request does this answer belong
to". A timestamp on the published observation answers the same question here,
and the staleness ladder (D023) needs that timestamp anyway — the slot already
had to hold a struct, so one more field is not new machinery. Futures would
additionally force async control flow into `GuidedTour` and change every
injected fake, breaking the collaborator contract that keeps the existing test
suite passing unchanged.

**The same shape, both directions.** Tier 2's request travels UI thread ->
worker through a second slot of exactly this kind (D028): one overwritten
`Tier2Request`, no queue, no future. A second request for the same step while
the first is still being read IS the same request, so overwrite is again the
discard. The asymmetry is that a result slot is self-expiring — a newer
observation replaces it — while a request STANDS until cancelled, which is why
`cancel_tier2` exists and the result direction needs no equivalent.

**The subtle part.** `AWAITING_USER_ACTION` must observe a strictly *later*
moment than `OBSERVING` did (D019). With a published slot that no longer holds
for free: if the worker has produced nothing new, `AWAITING` reads back the
same observation `OBSERVING` used, verification compares identical states,
concludes "nothing changed" forever, and every tour stalls on its first step.
So a slot that has not advanced is **not a failed verification — it is no
verification attempt yet**, and the loop keeps waiting without touching the
idle clock. The timestamp is what makes that expressible.

**What actually keeps the slot ordered.** A retired worker is still inside a
walk that may not return for tens of seconds, and `restart()` deliberately does
**not** join it — joining would block the UI thread for the join's full timeout
at exactly the moment the worker is wedged, which is the freeze D021 exists to
prevent. Ordering is guaranteed instead by the worker re-checking its own stop
Event immediately before publishing: a retired worker cannot publish at all, so
it cannot land a stale observation after the replacement's fresh one.

(An earlier draft of this entry claimed the join provided that guarantee. It
did not — the join timed out every time, and the pre-publish check was doing
the real work. The join has since been removed outright.)

---

## D023 — The staleness ladder, and why untimestamped means fresh

**Decision.** How old the last *confirmed-fresh* observation is decides what
the overlay shows:

| Age | Overlay shows |
|---|---|
| 0 – 1.5 s | the hint, unchanged — covers ordinary tick jitter, no false alarms |
| 1.5 – 5 s | the same hint, visibly dimmed — "last known, unconfirmed" |
| 5 s + | nothing, until perception recovers |

Past ~5 s the odds the underlying UI has actually changed are high enough that
showing nothing beats showing an increasingly-likely-wrong ring. Recovery to
fresh is **debounced** — a short run of consecutive successes, never one lucky
tick — so a flaky not-quite-hung app cannot flicker between states.

**"Confirmed-fresh" means the walk completed without raising**, regardless of
how many elements it found. A window that genuinely contains nothing matchable
is a successful observation; treating an empty result as staleness would make
a legitimately empty target look permanently frozen.

**`observed_at == 0.0` means untimestamped, and is treated as fresh.** That is
what synchronous or faked perception is. This is not a convenience: every
existing loop fake returns the same `Snapshot` on each call, so a strict "must
be strictly newer" rule would mean they never verify. The escape hatch is what
let the whole existing suite keep passing unchanged, which is the evidence
that the collaborator contract really was preserved.

**Feed the ladder only when the timestamp advances.** A hung worker leaves the
*previous* observation sitting in the slot. Calling `observed()` on every read
would re-confirm that stale observation every tick and reset the clock — so
nothing would ever dim, nothing would ever hide, and the health check (whose
stall signal is the ladder's age) would never fire either. The milestone would
have passed its tests and done nothing in the field.

**HIDDEN clears the hint; it is never passed to `set_hint`.** The painter
distinguishes only FRESH from everything-else, so handing it HIDDEN draws a
*dimmed* ring and the 5 s rung becomes dead code.

**Thresholds are judgement, not measurement**, and are constructor parameters
so they can be tuned against a real hanging app without a code change.

---

## D024 — Worker lifecycle: two signals decide, the heartbeat only explains

**Decision.** A dead-but-undetected worker would be a regression dressed as a
fix — the UI thread stays responsive and ESC still works, so nothing *looks*
wrong while the system has silently stopped guiding. That is harder to notice
than the freeze it replaced. Three signals, with strict roles:

- **staleness clock** — time since the last confirmed-fresh observation;
  detects "alive but not progressing";
- **`Thread.is_alive()`**, checked per tick — distinguishes "the worker raised
  and exited" from "still working". Without it a dead worker reports as merely
  stale forever;
- **heartbeat counter** — incremented every loop iteration regardless of
  success, **logged when the policy fires and never an input to it**. It
  separates "blocked in a slow UIA call" from "alive but looping through
  silent failures" *after the fact*, without that distinction quietly
  influencing behaviour.

**Policy:** on detected death, log the cause and the heartbeat, restart the
worker **exactly once**; if it dies again, end the tour with an explicit
reason rather than sitting silently stuck.

**Restart-once is load-bearing, not tidiness.** A blocked worker cannot be
joined and keeps reporting `is_alive()`, so the service clears its thread
reference to let a replacement start, leaving one orphaned blocked thread
until its bounded walk returns. Restart-forever would accumulate one such
thread per detection with nothing reaping them.

**Each worker generation owns its own stop Event.** Sharing one across
generations meant `stop()` set the flag and `start()` then *cleared it* for the
replacement — so when the orphan's 41 s walk returned it re-evaluated a cleared
flag and resumed looping forever. Two permanent publishers into one slot:
doubled COM load on an already-sick app, a slot whose timestamp could go
*backwards* (read downstream as freshness oscillating for no reason a user
could explain), and lost heartbeat increments corrupting the one diagnostic
meant to explain the failure afterwards.

**The two clocks must not race.** The grounding grace answers "is the target on
screen"; the health budget answers "is perception working". The second question
must resolve first, because the first is only meaningful once perception is
known to work. At the stock 10 s grace a dead worker made grounding fail every
tick and the tour gave up ~5 s *before* the 15 s health budget could fire —
telling the user `cannot find 'Export' on screen` about an element sitting
right there, and pointing them at their own application instead of at ours.

The first fix inflated the grace to outrun health. That was wrong twice over,
and the whole-branch review caught both halves. Health's worst case is **two**
budgets, not one — the check is suppressed for `dead_after_s` from tour start
(the ladder's age is infinite before the first observation), and the restart it
then fires grants the replacement another `dead_after_s` — so one budget still
lost the race on a target hung at *first contact*, the exact case this
milestone was built for: the tour gave up at 25.75 s, 4.25 s before health
could speak. And inflating the grace made a genuinely missing element take 40 s
to report, punishing the common case to paper over the rare one.

**The race is removed at its source instead.** The tick loop does not run at
all until the first observation lands, so grounding is only ever attempted
once a real observation exists. A grounding failure therefore means perception
*is* working and the element genuinely is not there — precisely when `cannot
find X on screen` is the correct thing to say. A worker that dies later leaves
its last observation in the slot, so grounding keeps succeeding against it, the
grace never starts, and the health check is left to name the failure. The grace
stays at its stock 10 s.

That guard is load-bearing for a second reason, and it is the more serious one:
ticking before the first observation let the empty placeholder snapshot become
a **verification baseline**. The loop advanced to DECIDING, grounding could
succeed off an observation that arrived between the two ticks, and `verify`
then compared against an empty `before` — where `ANY_MEANINGFUL_CHANGE` is
unconditionally true and `ELEMENT_APPEARS` matches anything already on screen.
A step could be marked complete that the user never performed. Spec §9 always
required staying in OBSERVING here; the placeholder snapshot quietly broke it.

**A restarted worker gets its own budget.** The staleness clock measures
observations, not workers, so a replacement inherits the staleness of the one
it replaced; judged on that, the very next tick ends the tour ~0.25 s later and
"restart once, then give up" degenerates into "give up". The fresh budget
forgives the replacement but does not exempt it — a replacement that never
observes is still caught, from a start time that exists. It deliberately does
not apply to `is_alive()`, which is a definitive answer available immediately.

**Both failures above were invisible to the tasks that introduced them** and
appeared only where the pieces compose. That is the argument for testing the
composed timeline, not only the rungs.

---

## D025 — A hung test window is a desktop-wide side effect

**Decision.** The hung-window fixture must reap its child unconditionally, and
tests that use it must never run concurrently with another test session.

**Why.** Any UIA enumeration that touches a non-pumping window pays the
SendMessage timeout, regardless of which *process* started the walk. Measured
on this machine:

```
two UIA-dependent test files, clean desktop        5 passed in   6.28 s
the same two, one hung window elsewhere on screen  5 passed in 100.13 s
```

A 16x tax on unrelated tests. Both tests still *passed* under it — which is the
signature of a timing-marginal test, and exactly how it shows up in practice:
add load and the margin disappears. Two failures in this repo were first
reported as "pre-existing flakes" and were nothing of the kind.

**Consequences.** `HungWindow` kills and reaps its child even when `__enter__`
itself raises — Python does not call `__exit__` when `__enter__` fails, so the
naive form orphans a real window on the user's screen with no cleanup path —
and bounds its handshake so a child that never signals ready fails fast instead
of hanging the suite. A fixture that outlives its test turns a transient 16x
tax into a permanent one.

---

## D026 — Stateful and time-based interactions get a sequence test

**Decision.** Where behaviour is a sequence of states over time, a test must
assert the ordered sequence end to end, in the assembled system. Unit tests of
each state, plus a test of the final state, do not substitute.

**Why, twice over.** This project has now been bitten twice by the same shape:
every component correct in isolation, the composition wrong.

- The tour's `snapshotter` called `ladder.observed()` on every slot read. The
  ladder was correct and unit-tested; the dimmed ring was correct and
  pixel-tested; the health policy was correct and unit-tested. But re-reading a
  wedged worker's stale observation re-confirmed it every tick, so the clock
  never advanced — nothing would ever dim, nothing would ever hide, and health
  would never fire. The whole milestone would have passed its suite and done
  nothing in the field.
- `WorkerHealth` read `ladder.age()` as `inf` before the first observation and
  ended the tour on tick 2, before perception had answered once.

Neither was visible to any test that existed at the time, and neither is an
exotic edge case — both sat on the primary path.

**The failure mode this guards.** A suite that passes completely while the
assembled system does nothing is close to the worst outcome available to a test
suite: it converts absence of evidence into confidence. Membership assertions
("the hint dimmed at some point") are not enough either — they pass when the
hint hides before it dims, or never comes back.

**In practice:** `tests/test_freshness_timeline.py`. One shared injected clock
— never two. The loop's deadline, the health budget, the staleness ladder, the
perception worker's throttle and `GuidedTour`'s grounding grace and idle
timeout all read the same source. That is not pedantry: a review of the first
draft found `GuidedTour` still on its own real-time clock, which silently froze
the grace-vs-health interaction — the THIRD composition bug of this milestone —
out of the very tests written to catch composition bugs.

The sequence is read from what the overlay was actually told to draw, asserted
as exact equality (a subsequence would permit a recovery that flickers back and
dies again), and the known bugs are carried as named regression cases rather
than folded into a generic happy path. Because the clock is injected, the whole
timeline runs in half a second and nothing sleeps.

**Fakes are part of the claim.** A hand-written fake that is more convenient
than reality makes the whole test theatre. The one here publishes on the
worker's own throttle rather than once per read — so the loop genuinely reads
the same observation twice, which is the condition the staleness guard exists
for — and freezes its heartbeat while wedged, because that freeze is the
heartbeat's entire diagnostic value.


## D027 — One write per tick: a two-step render is a laundering bug

**Decision:** the hint's display state is resolved once and emitted once per
tick, through `OverlayRenderer` as the single write path. Nothing paints a
provisional style and corrects it afterwards. `run_tour` no longer calls
`window.set_hint` at all; it calls `renderer.settle()`, which emits the tick's
state only if the loop has not already.

**The general principle, which is the part worth keeping.** *Any two-step
render where a paint can interleave with its own correction is a laundering
bug, regardless of which states are involved.* It does not matter that the
correction is "one tick later" or "microseconds later": the safety rule
governs what the system EMITS, not the odds a human catches the frame. If the
first write can differ from the settled one, the system has told the user
something it does not believe, and the fact that it later retracts it is not
visible to anyone.

**How it showed up.** `OverlayRenderer.show()` called `set_hint` with no
freshness, and `window.set_hint` defaults an unspecified freshness to FRESH.
So the opening paint of every hint was the confirmed-control style, and
`run_tour` then issued a SECOND `set_hint` later in the same tick with the
real display state. For an OCR-grounded target that meant a bright cyan ring —
"this is a control I have confirmed" — around a coordinate read off pixels,
which is the precise claim D006's never-act-for-the-user boundary exists to
stop the system making.

This was not a narrow race. `set_hint` ends in `UpdateWindow`, which paints
**synchronously**, so the provisional frame was not merely reachable — it was
drawn, every time, on every hint.

**Alternative considered and rejected: make the first write correct and leave
the second in place.** This was the first fix, and it is what prompted the
rule above. It makes the two writes agree *today*, which means the second one
is dead weight that silently becomes a correction again the moment the two
computations drift — and nothing would fail when they did. Narrowing the
window a `WM_PAINT` can slip through is not the same as closing it. The second
write is deleted, not synchronised.

**Alternative considered and rejected: two ways to supply the state.** The
renderer briefly accepted both an explicit `show(freshness=...)` argument and
an injected `freshness_source` callable. Nothing ever passed the argument. Two
ways to decide what to draw is the same defect one level up — the next reader
has to work out which wins — so only the callable survives. It is a callable
rather than a value because of a split in who knows what: the caller that
KNOWS the display state is `run.py` (it owns the staleness ladder and the
grounding source), but the caller that DRIVES the renderer is the loop, which
must stay ignorant of both, exactly as D019 and D023 require.

**Why "one write per tick" was not, by itself, the safety property.** An
earlier draft of this entry argued that reading the source at the write is
safe because the grounding source "is only ever changed by `DECIDING`, which
does not paint." That is false, and it is the sharpest case in D031's list:
`GuidedTour.tick()` ends in `settle()`, and `settle()` DOES paint on any tick
that did not already write. So a step whose source flipped `ocr` -> `uia` in
DECIDING had its old OCR centre repainted at the new UIA source by `settle()`
in RENDERING_HINT — a pixel guess drawn in the confirmed-control colour for a
full tick. One write per tick held perfectly; the property it was meant to
guarantee did not.

**What actually makes this safe.** Provenance is bound into the hint itself.
`renderer.py`'s `_Hint` is a frozen dataclass pairing a centre with the source
it was created with, and `show()` constructs both from the same
`GroundedTarget` in one statement — there is no window in which the centre is
this hint's and the source is another's. `run.py` no longer owns or supplies
the grounding source to the renderer at all: every repaint, including
`settle()`'s, resolves freshness by folding in `hint.source` (via
`display_freshness`), never whatever the wider system's grounding source says
now. A repaint can therefore only ever reproduce the display state its hint
was created with, not borrow a later step's confidence.

**Why `settle()` exists at all.** The loop calls `show()` only when it changes
WHAT is displayed — never when it changes how confident the system is. Without
a per-tick emission point the staleness ladder would be dead code: a hint
drawn FRESH at step start would never dim and never hide. `settle()` is that
point, and it is a no-op on any tick that already wrote, so "at most one write
per tick" holds without the caller tracking which case it is in.

**Provenance is required, not defaulted.** `OverlayRenderer` takes
`freshness_source` as a required keyword argument, and a source that answers
None resolves to INFERRED. There is no code path left that calls `set_hint`
without an explicit freshness, so a renderer that cannot say where its hint
came from cannot draw one as a confirmed control. The first attempt left the
permissive default in place and policed it with a test that scanned the
package for constructions that omitted it — rejected, because a scan is a
tripwire, not a guarantee: it passes the day someone adds a construction it
does not match, and what it guards is the same "unknown resolves to the most
trusting value" shape this entry exists to remove. Close it at the type, not
at the perimeter.

**The one coupling this leaves, and why it is closed twice.** A driver that
never calls `settle()` never asks the ladder what to draw. Nothing errors: the
hint stays exactly as drawn, never dimming, never hiding, while perception
hums along — the system looks fine and quietly stops degrading honestly, which
is the shape that has bitten this project three times.

The primary closure is structural: `GuidedTour.tick()` calls
`renderer.settle()` itself, as the last thing it does on every path. A driver
cannot forget it, because every driver ticks by definition. This does NOT
teach the loop about staleness — what to draw stays entirely behind the
renderer's `freshness_source`; the loop learns only that the renderer has a
tick boundary, which the loop already owns by being the thing that ticks. It
runs on the DONE and FAILED ticks too: both terminal paths call
`renderer.clear()` first, which marks the tick written, so nothing is emitted,
and "every tick settles" is a simpler invariant to hold than "every tick
except the last two".

`StalenessLadder` keeps a second, independent detector: it is the one object
that can see both that observations are flowing and that nothing consumes its
verdict, and after `unqueried_after_s` of that combination it says so once,
naming `settle()`. It is strictly narrower than the fold — it only fires for a
driver that wires THIS ladder and feeds it `observed()` — and its report goes
to stderr, which the user of a full-screen click-through overlay is not
watching. It is kept because it is nearly free and catches a renderer wired to
some other freshness source, not because it would be sufficient alone.

A first attempt shipped the detector as the ONLY closure, on a cost argument
about the protocol change. That was wrong on both counts: the change is about
six lines including three test fakes, and a warning nobody reads is closer to
a silent freeze than it looks.

**Tested as a standing property, not a regression case**
(`tests/test_first_paint.py`): the first paint equals the final display state
across the full cross-product of `Freshness` members and grounding sources —
generated from the enum itself, and including an unrecognised source, so a new
rung or a future perception tier is covered without anyone remembering to
extend it. An end-to-end arm buckets every overlay write of a real `run_tour`
by tick and asserts no bucket holds two, and the constructor and None-source
closures have their own cases. The unqueried signal is covered in
`tests/test_staleness.py`, in both directions — a driver that never reads is
reported exactly once, and a driver that reads every tick never is.

---

## D028 — Tier 2 triggers on grounding failure, never on an empty walk

**Decision.** OCR turns on when grounding fails for the CURRENT STEP — not
when a UIA walk returns few elements. Stickiness is per step and resets at the
step boundary. Two caps bound the cost, and exhausting the run cap ends the
step rather than freezing its last result.

**Why not "UIA returned nothing".** That trigger would never fire. Measured:
Chrome returned **43 elements in 0.31 s containing zero page content** — no
`Document` node, not one word of the page anywhere in the tree. UIA reported
success while being useless. Any trigger keyed on emptiness sees a healthy
walk and stands down.

This also avoids colliding with D023, which requires an empty walk to count as
a *successful observation* for staleness. The two never conflict because they
answer different questions: staleness asks "did perception complete recently",
grounding asks "can this step be located".

**Who decides and who reads.** The trigger is inherently a UI-thread concept —
only the tick loop knows which step is current and whether grounding just
failed — while the COST (capture plus OCR, 0.14-0.23 s measured on a 976x1028
window, scaling with captured AREA) belongs anywhere but the tick, where on a
4K screen it would eat D020's 0.5 s ceiling outright and bring back the D021
freeze. So the UI thread **decides and requests**, through a `Tier2Request` in
a second overwritten slot running opposite to the observation slot (D022), and
the perception worker **executes and publishes** — the read arrives as
`ocr_elements` on a LATER observation, tagged with `tier2_step`. No wait, no
join, no future: grounding may fail for a tick or two until the read lands,
which the grounding grace and the staleness ladder already cover. There is no
`wanted` flag; the ABSENCE of a request means "not wanted", because a flag
would have to be set False by exactly the callers that could instead clear the
slot, and a False request still carries a step index and a stale `grounded`
nothing would ever clear. Because nothing else ends a standing request, the UI
thread must cancel it when UIA answered and at every step boundary — a request
for step 3 serviced through all of step 4 delays the observations the user's
actual step is being grounded from.

**Why stickiness resets at the step boundary.** An app-wide flag would keep OCR
running for the rest of the tour after a single failure — paying full OCR cost
on steps that would have grounded through UIA in 0.3 ms, while still calling
itself a cheapest-first tier. Photoshop's text menus ground cheaply through
whatever UIA does expose even though its tool palette does not; the next step
must get to try tier 1 again.

**Why both caps, not one.** "Re-run only when the region changed" degrades into
"re-run every tick" against anything that animates — a loading spinner in
frame, a window being dragged, a video preview. A floor interval alone lets a
slow animation pace OCR forever; a run ceiling alone lets a fast one burn its
whole budget in a second. Both: **1.0 s minimum between runs, a ceiling of 20
CONSECUTIVE FRUITLESS runs per step.** A read that produces a groundable
target resets the count (`grounded()`), so the ceiling bounds unproductive
re-reading, not total work — a churning page that keeps re-grounding
correctly on OCR is the tier doing its job, not exhausting its budget.

**Why exhaustion is terminal.** When the ceiling is reached and the step still
cannot ground, tier 2 stops and the step is treated as ungroundable, feeding
the existing grounding grace and its give-up path.

The rejected alternative — let the last OCR result stand and simply age —
fails twice over. The ring keeps pointing at a coordinate the system has
stopped being able to confirm, which is the wrong point D006 exists to
prevent. And the step becomes **incapable of ever failing**: the user waits on
a hint that can never resolve and is never told why. A clean failure beats a
hint that cannot die.

The failure reason names the read failure rather than the generic "cannot
find", for the same reason D024 requires a dead worker to be named as one:
telling users their element is missing, when in fact we gave up reading the
screen, points them at their own application instead of at ours.

---

## D029 — `Windows.Media.Ocr`, and the floor of 95

**Decision.** Tier 2 reads with `Windows.Media.Ocr`, and a fuzzy match must
score **95** or better to ground.

**The engine, settled by measurement rather than argument.** Both candidates
run against identical captures of four real application screens:

| | cold start | full 1938x1038 frame | cropped | recall @90 |
|---|---|---|---|---|
| `Windows.Media.Ocr` | **0.01 s** | **0.17-0.23 s** | **0.03 s** | **22/23** |
| RapidOCR (onnxruntime) | 0.68 s | **39-66 s** | 1.6-2.8 s | 16/23 |

RapidOCR is not slower — it is disqualified. 39 seconds on a window is roughly
200x the estimate, and even cropped it exceeds a tick. `Windows.Media.Ocr`
wins on every axis and ships with the OS, so there is no model download and no
network (D017).

**Stock PaddleOCR was ruled out WITHOUT measuring it.** A few-hundred-megabyte
deep-learning runtime plus a first-run network fetch, inside an application
that otherwise touches no network, conflicts with D017 regardless of how
accurate it is. No accuracy number could have changed that, so spiking it
would have meant installing the heaviest candidate available purely to reject
a decision already made on principle. This refines D003's engine choice; it
does not reverse its tiering.

**The floor is measured, and it could not have been guessed.** Sweeping the
fuzzy threshold across all four screens, the binding case is a step claiming
`Uploads` against an OCR read of `upload`, scoring **92.3**. Those are two
real, different Canva surfaces one character apart. The OCR documentation's
suggested 0.85 would have pointed at the wrong one on the first real screen
tested. At 95, zero false matches across every screen.

**One bar is doing two jobs, and that is why 95 is conservative.** The design
called for two independent floors — read confidence AND match score, neither
able to borrow slack from the other, because a weak read and a loose match
otherwise average into something that looks acceptable and is not.
**`Windows.Media.Ocr` exposes no per-word confidence.** That is stated plainly
rather than quietly dropped: the two-floor design cannot be built on this
engine, the match score carries both jobs, and the threshold is set high for
that reason rather than tuned for recall.

**The language-pack risk was gated before implementation started.** The engine
needs an OCR recognizer pack, and installing a missing one requires
administrator rights — "end users need admin to use a fallback tier" would be
a distribution blocker independent of accuracy. Verified on a SECOND Windows
machine before any code was written: `en-GB` and `en-US` present, both engine
constructors returning objects, no elevation required. Two machines is not a
distribution study. If tier 2 ever reports itself unavailable in the field,
this is the first thing to check.

---

## D030 — OCR results are never promoted, and rung 3 excludes them

**Decision.** Nothing tier 2 produces is ever written to the knowledge base,
and OCR elements are barred from grounding rung 3.

**Promotion is blocked by an explicit provenance guard, not by construction.**
`promote()` in `ghostcursor/reasoning/grounding.py` checks the grounded
target's `source` directly and refuses anything that did not come from a
confirmed UIA control. It used to be true only incidentally, because OCR
elements carry no AutomationId and an earlier guard on that field caught them
as a side effect — which made "never promoted by construction" a claim
resting on a coincidence of empty strings, not a real barrier. A future tier
that DID supply an id (tier 3, the VLM, is exactly this case) could have
quietly started writing pixel-derived rows into the knowledge base. The
provenance check is what actually closes that; `tests/test_regression_ocr_fixes.py`
isolates the guard.

So the knowledge base stays UIA-only and provably clean, and tier 2 is pure
runtime fallback. A user who deletes the database loses nothing OCR produced,
because OCR produced nothing that outlives the tick.

**Why rung 3 must exclude OCR — the floor is decorative without it.** Rung 3
is not an exact match. It is a case-insensitive **substring** test inherited
from an era when every element came from UIA and names were authoritative, and
it runs BEFORE rung 4.

Left unfiltered, an OCR element reaches it and matches with no score threshold
whatsoever. A step claiming `Edit` substring-matches OCR reads of
`Edit a PDF`, `Magic Edit` and `Editor` alike, and rung 3 returns whichever the
disambiguator happens to pick — with D029's floor of 95 never consulted.

Rung 3 therefore filters to `source == "uia"`. That leaves two rungs OCR can
still reach, and both stay safe under the floor: rung 4 applies
`OCR_MATCH_FLOOR` at 95 directly, and rung 2 admits OCR only on byte-exact
name equality — a strictly higher bar than a 95 fuzzy score, so it never
undercuts the floor. What rung 3's exclusion removes is loose, unscored
matching on unconfirmed text, not OCR as such.

This was found while writing the implementation plan, not while designing: the
spec asserted rungs 1-3 were all exact and built the safety argument on rung 4
being the only loose one. Reading the code showed rung 3 had been a substring
test all along.

**The failure this guards against is not hypothetical.** Multi-line labels
were the dominant OCR failure across all four screens — single-line labels
read perfectly (`BG Remover`, `Magic Edit`, `Upscale`, `Blur`, `Select area`
all scored 100.0) while wrapped ones failed systematically, and failed in the
worst available way:

```
Magic Eraser  ->  read as 'Eraser'      66.7
BG Generator  ->  read as 'Generator'   85.7
Magic Expand  ->  read as 'Magic Edit'  72.7   <-- a DIFFERENT REAL TOOL
```

`Magic Expand` matching `Magic Edit` is two real buttons side by side in
Canva's photo editor. A user following that hint applies the wrong operation
to their image. Reassembling wrapped reads before matching removes the
mechanism rather than thresholding above its symptom — and its false-positive
direction is tested as hard as its recall direction, because a merge of two
unrelated adjacent labels could invent a target neither part would match.

---

## D031 — An invariant must imply the property, not merely correlate with it

**Decision.** Every fix in this project must state, explicitly, the property
it protects AND the invariant it enforces — and then answer whether the
invariant genuinely *implies* the property, or merely correlates with it
across the cases tested so far. An invariant is accepted only alongside
either a named case that would satisfy the invariant while violating the
property, or a demonstration that no such case exists. This carries the same
standing as D018's mutation testing, and is adopted for the same reason: a
green signal that does not mean what it appears to mean.

**Call the failure mode a FALSE GREEN.** The project has hit it four times,
at four different layers, and the repetition is the argument:

1. **The escapability test's flat wall-clock budget.** It asserted total
   elapsed under 7.0 s across five ticks. The property was "no single tick
   blocks, because ESC is polled between ticks." Total elapsed does not imply
   that: a regression costing ~1.1 s per tick — already double D020's 0.5 s
   ceiling — summed to under budget and passed silently. Fixed by asserting
   the maximum gap between consecutive ESC polls, which is scale-free and
   cannot be diluted by fast ticks.

2. **The staleness ladder fed on every slot read.** Every unit test of the
   ladder, the ring colour and the health policy passed. The property — "the
   display degrades honestly as observations age" — held in none of them,
   because re-reading a wedged worker's stale observation re-confirmed it
   each tick and the clock never advanced. Nothing ever dimmed, nothing ever
   hid, health never fired.

3. **Health killing the tour on tick 2.** Each component correct in
   isolation; the composition wrong. `ladder.age()` is infinite before the
   first observation, so the tour ended before perception had answered once.

4. **The single-write render invariant** (D027). "Exactly one `set_hint` per
   tick" held perfectly. The property it existed to guarantee — "no paint can
   show a pixel guess in the confirmed-control colour" — did not.
   `grounded_source` flips in DECIDING while the renderer's centre updates a
   tick later in RENDERING_HINT, so `settle()` repaints the OLD OCR centre at
   the NEW UIA source: cyan, for a full ~250 ms tick, at a coordinate the UIA
   rect may not agree with. Reproduced against the real renderer as
   `[('set',100,100,INFERRED), ('set',100,100,FRESH)]`.

**Case 4 is the sharpest one, and it is worth drawing out why.** The
invariant was not weakened, not misimplemented, and not untested. It was
*satisfied*, and it was the wrong invariant — it counted writes when the
property was about what any single write could show. A counter cannot see
that.

**The structural fix that followed generalises.** The two facts had to
become one atomically-constructed value. A hint's provenance and its
coordinate must not be separately updatable fields, because any two fields
updated on different ticks can be read in a combination that never
legitimately existed.

**What this does not mean.** Not that invariants are useless, and not that
every fix needs a formal proof. The requirement is one honest paragraph
naming the property, the invariant, and the gap between them — the same
weight D018 already asks for a mutation.

---

## D032 — No task is reviewed by the agent that produced it

**Status: ENFORCED GATE, not an aspiration.** Promoted after a SECOND
independent occurrence on the same milestone, and the second was worse than the
first. Occurrence one (P9): the controller finished a documentation task itself
and three of four later-found defects were in that work. Occurrence two (D034):
the controller asserted an unrecorded measurement into a brief, and it reached
the documentation as a cited fact arguing to weaken a safety floor. Both
bypassed the normal task review — one by the controller writing the work, the
other by the controller supplying the facts.

**The gate names the controller explicitly**, because the subagent workflow
already reviews every dispatched task; a rule phrased only as "tasks get
reviewed" reads as already-satisfied and changes nothing. What must be reviewed
is any output the controller produced or any fact the controller supplied,
including prose, documentation, and figures written into a dispatch brief.
Nothing the controller authored is ground truth until something else has read
it.

**Decision.** Every task gets a review by someone who did not write it. Code
and documentation alike — prose gets no exemption. A self-review supplements
an independent review; it never replaces one.

**What forced it.** During the tier-2 milestone, the controller finished the
documentation task itself after the assigned implementer hit a hard session
limit mid-task. It seemed low-risk: the task was prose, and every fact was
already recorded in the working ledger.

The final whole-branch review then found four documentation defects, **three
of them in exactly that unreviewed work** — including a docstring that had
been deferred twice, each time on an explicit promise the documentation task
would close it, and which that task then only half-closed. The two
docstrings that were caught earlier in the milestone had both been found by
independent reviewers, not by their authors.

**The lesson, precisely.** The author of a piece of work is the one person
who cannot see the assumption they made while writing it. That is not about
care or competence — the controller in question had strong context and was
being deliberate. Fresh eyes are a different instrument, not a more diligent
version of the same one.

**Why documentation specifically is not an exception.** This project has now
fixed three docstrings that confidently described behaviour the code did not
have — captures said to go through a function they never call, OCR boxes
said to be in screen coordinates when they are frame-relative, and a claim
that OCR text has exactly one route into grounding when it has two. Each is
the dangerous kind of wrong: a future reader could "fix" the code to match
the document. Documentation that misdescribes behaviour is a latent code
change waiting for someone conscientious.

**Cross-reference.** D018 and D031 are the other two standing rules of the
same family — all three exist because something looked verified and was
not. **D033** carries the concrete evidence for this entry — the specific
ruling that produced it and what that cost — and
`docs/superpowers/ledgers/2026-08-15-perception-tier-2-ocr-ledger.md` holds
the full execution record, kept outside the throwaway workspace precisely so
this evidence cannot be deleted by routine cleanup.

---

## D033 — What the tier-2 milestone's rulings cost, and where they live

**Decision.** Execution rulings — the calls made on the human partner's behalf
while a plan is running, without stopping to ask — are preserved in
`docs/superpowers/ledgers/`, not only in the throwaway execution workspace.
The load-bearing ones are summarised here.

**Why this entry exists at all.** The tier-2 milestone produced thirteen such
rulings. They lived in `.superpowers/sdd/<plan>/progress.md`, a directory whose
entire lifecycle is designed to be deleted once a branch merges. The single
most valuable thing that milestone learned — that self-review has a
demonstrated, repeated blind spot — was sitting in a file the normal process
would have removed by habit. That is a bad place for evidence. The ledger is
now copied into `docs/superpowers/ledgers/` and committed.

### The ruling that was wrong, and what it cost

**P9 — the controller finished a task itself rather than dispatching it.**
The documentation task's implementer hit a hard capacity limit mid-task. The
work remaining was prose **plus a one-line `re.escape` fix**, every fact was
already in the ledger, and dispatching
a fresh agent would have meant re-deriving context the controller already held.
Finishing it directly looked obviously correct.

The final whole-branch review then found four documentation defects. **Three
were in exactly that unreviewed work** — including a docstring that had been
deferred twice, each time on an explicit promise the documentation task would
close it, and which that task then only half-closed. The two docstrings caught
earlier in the same milestone had both been found by independent reviewers,
never by their authors.

This is the evidence D032 cites. It is recorded here rather than left implicit
because "no self-review" is easy to agree with in the abstract and easy to
rationalise away in the moment — the rationalisation that produced it was
sound-sounding and specific, and it was still wrong.

### The rulings that carry forward

**P12 — a surviving mutation is a finding, not an inconvenience.** A test
asserting that nothing OCR-derived reaches the knowledge base passed even with
both new guards removed, because a pre-existing empty-id check in
`ObservationStore.record()` covered the same cases. The property held; the new
invariant was merely correlated with it. The agent reported this plainly
instead of adjusting the test. One more unit test now isolates the guard using
a fabricated non-empty-id, non-`uia` target — the case that matters the day a
VLM tier (D003) produces elements with synthetic ids and the empty-id backstop
stops covering them. See D031.

**P7 — process escalation rules are heuristics, not laws.** The convention is
that a fix loop surviving three rounds goes to a fresh implementer on a
stronger model, because a loop that long usually means the implementer cannot
see its own problem. That was not the situation: each round had found real
defects beyond what it was asked for, including a mutating query called twice
per painting tick that nobody had pointed at. Keeping it was right, and the
deviation is recorded so the next person can weigh the same call.

**P8 — a reviewer's disagreement is worth more than a tidy loop.** An
implementer rejected a structural fix on cost and substituted detection. The
reviewer priced the structural option at roughly six lines and showed detection
closed a strictly narrower set — it fires only for a driver that wires THIS
ladder and feeds it `observed()`, so a future driver with a different
`freshness_source`, or none, freezes with no signal at all. The structural fix
won **without displacing the detector: the ruling was to fold `settle()` into
`GuidedTour.tick()` as the primary closure AND KEEP the detector as
belt-and-braces**, which is why `staleness.py` still carries its
unqueried-ladder warning. Implementing it
surfaced something neither had anticipated: the fold had to happen inside a
helper rather than per-branch, because the branch it would otherwise have
missed was the one the tour *dwells* in.

**P11 — stopping is sometimes the work.** With capacity exhausted and three
regression tests unwritten, the branch was left unmergeable overnight rather
than have the controller write and solely review the tests guarding the
milestone's most dangerous defect. A green suite that does not guard its
properties is a false green (D031); shipping one to avoid a delay trades a
day for a permanent hole.

**P13 — documentation drift blocks a merge.** The final re-review found that
D027, D028 and D030 had come to state the opposite of the code they document —
D027 still asserting the very claim the milestone's worst defect disproved. A
decision record that contradicts the code is worse than none, because it is the
artefact a future reader trusts most. Fixed before merge, by an agent that had
written neither the code nor the entries.

### What this does not license

Recording a ruling is not the same as it being right. P9 is in this list
precisely because it was wrong, and the honest lesson is that its reasoning
felt sound while being made. The value of the ledger is that the calls are
inspectable afterwards — not that making them unilaterally is costless.

---

## D034 — A measured number in documentation must name where it is recorded

**Decision.** Any figure presented in documentation as measured — a timing, a
count, a score, a threshold — must point to where that measurement is written
down. If it is not in a committed document, it is not citable, and the prose
must either record it properly first or not present it as evidence.

This applies with equal force to the instructions given to another agent.
Asserting a number into a brief is publishing it: whoever receives it will
write it down as fact, correctly trusting the person who said it.

### The incident

The tier-2 milestone set OCR's fuzzy-match floor at 95, a number the spike
measured and argued for at length. While briefing a documentation pass, the
controller wrote that the spike recorded Acrobat reading **"24 of 24 at floor
85"**, and that 85 was rejected because it admits `Magic Expand` matching a
read of `Magic Edit`.

The findings document records only **21 of 24, at floor 95**. It says nothing
about 24 of 24 and nothing about floor 85 for Acrobat recall. The agent, having
no reason to doubt the brief, wrote the citation faithfully.

**The number was not invented.** It came from a real scoring run earlier in the
same session — measured, correct, and never written into any document. That is
precisely what makes this worth its own entry: "but I did measure it" feels like
a defence and is not one. The failure was **laundering ephemeral evidence into
cited authority** — taking something true but unrecorded and presenting it as
though the written record supported it. A rule against fabrication would not
have caught it, because nothing was fabricated.

**And the justification attached to it was inverted.** `Magic Expand` ←
`Magic Edit` scores 72.7, so a floor of 85 *excludes* it. The findings table
gives Acrobat `>= 85` for a different pair entirely, and the binding case
against 85 is Canva Home's `Uploads` ← `upload` at 92.3.

### Why this is not D032

D032 exists because documentation drifts from code when nobody independently
checks it. That is an ordinary failure and the tier-2 milestone produced ten
instances of it in a single unreviewed slice — stale claims that were true when
written.

This is a different shape and a worse one. Nothing had drifted. A specific
number entered the record with no source, in a direction that **erodes a safety
threshold**: a future engineer tuning `OCR_MATCH_FLOOR` would check the spike,
find that 85 catches the example cited against it, and conclude 95 is
over-conservative. They would be citing this project's own documentation as
authority for weakening the exact protection the spike existed to establish.

The two need different fixes. D032's is *review the unreviewed*. This one's is
*a number must carry its provenance* — a rule about what may be written, not
about who checks it afterwards. Review caught this one, but only because it was
specifically hunted; a provenance rule prevents it being written at all.

### In practice

- Before stating a measurement, locate it in a committed document and cite it.
- If it exists only in a session, a scratch run or a conversation, record it
  first — or write "not recorded" rather than implying a source.
- The same rule binds instructions to another agent. A number asserted in a
  brief is a number published.
- When rejecting an option on measured grounds, cite the measurement that
  actually rejects it. A plausible-sounding wrong reason is worse than none: it
  survives scrutiny long enough to be repeated.

Related: **D018** (mutation-verify rather than assume), **D026** (sequence tests
for stateful behaviour), **D031** (an invariant must imply the property),
**D032** (independent review). All five exist because something looked verified
and was not.

---

## D035 — A warm-up grace period before tier 2 may be requested, keyed by window handle

**Decision.** `run.py` escalated to tier 2 the instant grounding failed for the
current step — including the first tick of a cold start, before a Chromium
application's accessibility tree has finished populating. A `WarmUp` object
now suppresses `service.request_tier2()` for a budget after a window's first
failed grounding, and closes permanently for that handle the moment UIA
grounding succeeds against it (`WarmUp.allows_tier2` / `WarmUp.note_grounded`,
`ghostcursor/perception/warmup.py`). `run.py`'s tier-2 request site now calls
`warmup.allows_tier2(target_hwnd)` before `service.request_tier2(i)`, and the
UIA-success path calls `warmup.note_grounded(target_hwnd)`. `Observation` now
carries `target_hwnd: int`, published by the perception worker, so the UI
thread can key warm-up state without crossing an apartment-bound UIA object
across the thread boundary (D021).

**Why not readiness detection.** Every attempt to tell "not yet ready" apart
from "will never have content" was ruled out by measurement, not preference —
see `docs/superpowers/specs/2026-08-19-cold-electron-probe-findings.md` (D034).
"Window furniture present, no content" is TRANSIENT in a cold VS Code and
TERMINAL in Adobe Acrobat, the same shape at any threshold. The element count
is not even monotonic in steady state, so comparing consecutive observations
to detect convergence is unsound. What the system already has is a perfect
readiness signal — grounding itself succeeding — so the fix is patience, not
a new detector.

**The budget: 2.0 s, and its measured basis.** VS Code grounded four targets
(`File`, `Edit`, `Explorer`, `DECISIONS.md`) 0.57 s after the window appeared
in one cold run and 0.39 s in another, per the targeted-grounding sweep in
`docs/superpowers/specs/2026-08-19-chromium-warm-up-design.md` §"The budget
was swept, not guessed" — a fifth target, `Terminal`, grounded at 1.75 s in
the first run and never within 14 s in the second, which the same section
treats as absent rather than slow. Discord, measured from the real window
(its splash excluded — see below), grounded all six targets 0.92 s after it
appeared, per `docs/superpowers/specs/2026-08-19-cold-electron-probe-findings.md`
§6.4. No element in either app was ever observed to ground
slowly-but-eventually — it was either fast (within ~2 s) or absent — so a
larger budget buys nothing; it cannot rescue a target that is simply absent.
2.0 s covers every target that grounded at all in the VS Code sweep and gives
roughly double Discord's figure as margin.

**Keyed by window HANDLE, not by the title regex — and the reason is
measured, not defensive.** Discord's cold start puts up a window titled
`Discord Updater` that fully matches the same title regex as the real Discord
window — visible, non-minimised, on-screen — and lives for roughly five
seconds before the real window exists, as a distinct HWND (see the findings
addendum, §6.3). A warm-up keyed by title would open on the splash, spend its
entire budget there, and leave the real window — whose tree is ready in
0.92 s — with no allowance at all: escalating straight to OCR, exactly the
failure this design exists to prevent. This was found by deliberately probing
an application chosen to falsify the design (Discord loads content over the
network, so a slow-but-eventual arrival should have shown up there if it
existed anywhere), not by review.

**The accepted cost.** A genuinely UIA-blind application — Adobe Acrobat,
tier 2's entire reason for existing (D028) — now waits the full budget before
OCR engages, on every cold start, permanently; it will never ground and so
never close its own warm-up. This is why the budget is 2.0 s and not the 5.0 s
an earlier draft proposed — every second here is a second Acrobat's user waits
staring at an unringed screen.

**Window-churn risk — unmeasured, and a diagnostic instruction, not a
caveat.** If tier 2 ever appears not to fire on some application, check
`WarmUp.opens` before anything else. It is a diagnostic-only counter, read by
nothing that decides policy — the same shape as the worker heartbeat under
D024 — incremented once per distinct handle that opens a warm-up. A count in
the dozens means the application is recreating its top-level window faster
than the budget, so warm-up keeps re-opening on each new handle and tier 2 is
suppressed permanently, with no other visible symptom. This scenario has never
been produced or measured; it is named here so it is checked first, not
rediscovered by debugging OCR from scratch.

**Measurement limitations, carried forward from the design spec's §8 "What
the measurements do not establish" so a future reader does not have to go
find it:**
- Slack and Teams were not tested. Only VS Code and Discord were measured.
- The Discord figure (0.92 s, all six targets) rests on a **single** valid
  run. Two earlier runs measured the `Discord Updater` splash window instead
  of the real application and were discarded once the cause was found — they
  are not corroborating data points for the real window's figure.
- Chrome's element-count fluctuation data (used to rule out readiness
  detection) came from an already-loaded page with a cold accessibility tree,
  not from a cold application start; it speaks to steady-state noise, not to
  the cold-start shape this decision is about.

Related: **D021** (perception worker thread, apartment-bound UIA objects),
**D024** (a diagnostic-only counter, not read by policy), **D028** (tier 2
triggers on grounding failure — this decision narrows *when* that trigger is
armed, not what it is), **D034** (this entry's every measured figure is cited
to the document that recorded it).

## D036 — Fix the class, not the instance: sweep for siblings before closing a finding

**Decision.** When a review finds a defect, treat it as an instance of a class and
grep for the other instances before marking it fixed. Record in the fix what was
swept, not merely what was changed. A finding closed on one instance is closed on
one instance, and nothing about having fixed it makes the siblings less wrong.

**What it cost to learn.** The Chromium warm-up branch. Final whole-branch review
found `first_matching_hwnd`'s docstring overstating a guarantee — claiming it and
the walk "both go through `windows_matching`", when `iter_elements` merely *gates*
on that enumeration and hands final selection to pywinauto, so with several
matching windows the two can name different ones. It was corrected, reviewed,
verified and closed.

The identical claim survived on `Observation.target_hwnd`'s field comment in
`ghostcursor/perception/service.py` — same overstatement, same branch, same
review pass — and reached the pull request, where an outside reviewer found it.
Nobody swept. The fix was applied where the finding pointed and stopped there.

**Why this is not already covered.** D032 requires an independent read of what
the controller authored, and it worked: the docstring defect WAS found by an
independent reviewer. D018 mutation-verifies behaviour, which a comment has none
of. Neither rule says anything about the scope of a fix once a finding is
correctly identified, and that is the gap this closes.

**The pattern this is the third instance of** (a fourth was added by the
wrong-action milestone — see D038). Each review layer catches a class
of defect the layer inside it cannot see, by construction:

| Layer | What it caught that the inner layer structurally could not |
|---|---|
| Whole-branch review | A standing tier-2 request never retracted across a window change — an interaction between three tasks each individually correct and each individually reviewed as correct. Task-scoped review cannot see a seam. |
| Controller mutation | A tick-loop test that passed with the warm-up gate deleted from `run.py`. Five green stability runs, a docstring explicitly claiming non-triviality, and a passing suite all missed it. Only mutating the GATE — not re-running the test — exposed it. |
| Outside review (PR) | The sibling docstring above, in a fix the whole-branch review had itself produced and closed. |
| Whole-branch review, again | `focus_visited` recording RESTING focus rather than focus that MOVED (D038). It passed every task gate that could have seen it, including a dedicated worker review on a stronger model, because at task level the code did exactly what it claimed. The defect existed only in the relationship BETWEEN intervals — and the suite certified it, since the dedup test fed a constant reader and asserted the id was still reported. |

The generalisation is that **no review layer can audit its own blind spot**, which
is the same argument D026 made about components ("every component correct in
isolation while the assembled system did nothing") applied to review itself. It is
the standing case for keeping whole-branch review a gate rather than a courtesy
when everything upstream already looks clean.

**Not adopted:** mechanical enforcement. See `docs/superpowers/FOLLOWUPS.md` — that
trigger fires on evidence laundering specifically and explicitly excludes
documentation drift, which this is. It remains at one occurrence, deliberately.

Related: **D032** (independent read — necessary, and shown here to be insufficient
alone), **D018** (mutation-verification, which caught the false green), **D026**
(components correct in isolation while the assembly is not; this applies the same
shape to review layers), **D034** (the failure family both PR comments landed in:
prose asserting a guarantee the code does not enforce).

---

## D037 — Wrong-action feedback fires on focus, never on element churn, and only the tick loop decides

**Decision.** The perception worker samples UI Automation focus in ~50ms
slices during its inter-walk wait and publishes `Observation.focus_visited` —
the distinct in-app AutomationIds focus **visited** since the last
observation, not merely the one it rests on. In `AWAITING_USER_ACTION`, if
verification is unsatisfied and `focus_visited` names a control that is not
the step's grounded target, the loop prints one line naming what was touched
and returns to `OBSERVING`, which re-grounds and re-shows the ring through the
existing render path. Satisfied verification always wins first: a step that
completed despite a detour is not interrupted to be criticised for it.

**Why focus, not `elements_changed`.** The loop already had a signal for "the
world changed unexpectedly" — the `elements_changed` branch already
re-observes on any element-identity change. It cannot be the wrong-action
signal, because element identity drifts with no user action at all: VS
Code's element set was measured churning roughly 10% in steady state, on a
real workload, well after startup finished
(`docs/superpowers/specs/2026-08-19-cold-electron-probe-findings.md` §3).
Announcing "you did the wrong thing" on application churn is the Clippy
failure this whole loop exists to avoid. Focus changes overwhelmingly because
a user acted on a control; unlike the element set, it was not observed
drifting on its own — asserted from the design, not separately measured.

**The measured numbers, and where they live.** Per D034, every figure below
is cited to the document that recorded it, not restated from memory.
`docs/superpowers/specs/2026-08-20-wrong-action-feedback-design.md` declares
itself the PRIMARY RECORD for the focus numbers — they come from two
throwaway probes, not kept in the repo, and are written down there first:

- `IUIAutomation::GetFocusedElement`, 40 samples: median **2.66ms**, none over
  100ms or over 500ms (D020's tick ceiling) — design spec §2.1.
- Re-probed against `tests.uia_app.SyntheticApp`'s real controls, the id
  `GetFocusedElement` reports matches the id a tree walk reports exactly —
  Export button `1001`, Delete button `1002`, filename edit `1004`, all three
  — design spec §2.2. This is what makes the comparison against the grounded
  target meaningful rather than approximate; an earlier probe against a
  console window returned empty AutomationIds for all 40 samples and looked
  fatal until re-pointed at real controls.
- Walk duration **0.18–0.70s**, tier-2 capture+OCR **0.14–0.23s** (the latter
  already recorded at D028) — design spec §2.3 and §7.

**The worker perceives, the loop decides — D028's split, applied again.** The
worker filters on exactly two perception facts: focus is inside the target
process, and the focused element has a non-empty AutomationId. It does not
know which step is current or what it is grounded to — only the tick loop
does, the same division D028 drew for tier 2 (UI thread decides and requests,
worker executes and publishes). Only primitives cross the thread boundary
(D021): `focus_visited` is a `tuple[str, ...]`, never a retained COM element.

**The re-hint reuses `OBSERVING`, not a second write path (D027).** No
`renderer.show()` call was added to the wrong-action branch. `set_hint` ends
in `UpdateWindow`, which paints synchronously — a second corrective write is
not a narrow race, it is a second frame that definitely reaches the screen.
Routing the re-hint back through `OBSERVING` keeps the single-write-per-tick
invariant D027 exists to protect, and re-grounds first on its own merits: a
wrong click may have opened a dialog and moved the target.

**Two different caps, because they are two different situations.** Wrong-
action re-hints cap at **3** per step; the idle re-hint cap stays **1**,
unchanged. Idle means the user is doing nothing, and a second nudge on top of
the first is nagging. A wrong action means the user is actively trying, and
answering each attempt is help. The console MESSAGE, unlike the re-hint, is
deliberately **uncapped** — it is bounded by real user actions, not by wall
clock, so it cannot produce the unbounded nagging the re-hint cap exists to
prevent. Capping the message too would tell a user who keeps genuinely trying
and failing LESS the harder they struggle, which is backwards for a system
whose whole purpose is teaching.

**The OCR blind spot, stated plainly.** Wrong-action feedback does not exist
on OCR-grounded steps. OCR elements carry no AutomationId, so there is
nothing to compare `focus_visited` against, and the loop stays silent by
construction rather than by a special case. This is not a gap discovered
later — it falls out of the firing policy and is recorded here so it is
known rather than rediscovered.

**The deferred alternative, and the honest reason it stays deferred.** Native
UIA focus-change events (`AddFocusChangedEventListener`) would close the
sampling gap entirely and are not built. An earlier draft of the design
justified the deferral on the gap being "inside 50ms, faster than a human
performs two deliberate clicks" — wrong by roughly an order of magnitude: 50ms
is the slice interval, not the gap the slicing leaves open. Focus is not
sampled during the walk or during a standing tier-2 request at all, so the
real contiguous blind window is **0.18–0.93s** (walk plus tier 2). Focus is
sampled for roughly **18–53%** of wall time (the 0.2s sampled interval
against that 0.18–0.93s unsampled), so the blind window is the MAJORITY of
it, not a minor gap in it — a wrong-then-right round trip landing inside that
window is well within normal human click speed, not faster than it (design
spec §7, corrected during this milestone after being caught by the
independent review gate rather than self-caught — commit `6ec6c97`, "fix:
address review Important findings on wrong-action focus sampling"; the corrected figure is itself the kind
of number D034 exists to keep honest, and the catch is one line of evidence
D032 pays for itself). The deferral still stands, but for the real reason: native
events arrive as COM callbacks on RPC-managed threads and would need
marshalling into the worker's apartment — exactly the D021 area this project
has already paid to avoid, not because the gap is negligible.

**`FOCUS_MOVES_TO`.** The verification kind that had always raised
`NotImplementedError` because focus was never tracked is enabled by this
milestone, with its own tests, rather than riding in silently on a feature
that merely happened to unblock it. It compares against
`Snapshot.focused_automation_id`, which is populated only by the walk-start
sample — so this rule verifies at walk cadence (0.4–1.0s) and can miss a
focus move entirely, while the wrong-action path samples 4x more finely from
the same worker. No recipe uses the rule today, so the asymmetry is inert in
production, but it is recorded here rather than left to be discovered.

**Only a focus TRANSITION is reported, never a resting hold — and the first
read only seeds.** A Critical defect, found and fixed within this milestone:
`focus_visited` originally recorded whatever focus was found to be on at each
sample, so a control that never lost focus at all was re-appended on every
single observation for as long as it held focus, and the loop nagged a user
who had done nothing since the last tick. The fix, in
`PerceptionService._record_focus` (`ghostcursor/perception/service.py`), is
to compare each read against a `last_focus_holder` that survives
`visited.clear()` at every successful publish — it lives for the whole worker
generation, not just one interval — and append only when the read differs
from what that holder last saw. Two consequences follow directly and both are
worth stating plainly rather than leaving them to be found in a docstring:

- The id already holding focus when the worker starts is not a "visit" at
  all. The very first non-empty focus read of the worker's lifetime only
  seeds `last_focus_holder`; it is never appended to `visited`. Whatever the
  user happened to be focused on before the tour began is not reported as
  having been touched.
- **Re-clicking a control that already has focus produces no transition.** If
  a user's wrong click lands on the same wrong control twice in a row with no
  intervening focus change, the second click is invisible to this mechanism —
  it is told once, on the first transition onto that control, and then not
  again for as long as focus stays there. This is the correct side of the
  Clippy tradeoff (repeating "that's still wrong" on every tick the user
  hasn't moved on would be exactly the nagging D037's design set out to
  avoid), but it is a real behaviour, not a hypothetical edge case, and
  nobody had written it down before this fix.

`tests/test_focus_service.py::test_the_first_focus_read_only_seeds_and_is_never_reported`
guards the seeding rule specifically — mutating the early-return in
`_record_focus` away (so the first read appends instead of only seeding)
passed all nine of the file's pre-existing tests and is caught only by this
one, which is the exact D018/D031 shape (a real invariant with no failing
test behind it) this project has been burned by repeatedly on this milestone.

Related: **D021** (only primitives cross the worker/UI thread boundary),
**D027** (one write per tick — why the re-hint reuses `OBSERVING`), **D028**
(the worker-perceives / loop-decides split, applied a second time), **D031**
(the seeding branch's own mutation-survivable shape), **D034**
(every number above named to its record; the §7 correction is this rule
applied to the project's own prior draft).


## D038 — The brief is the least-reviewed artefact, so reviewers must verify it rather than defer to it

**Later correction.** The nine below is the count as of this entry being
written. External review of the pull request then found two more — an empty
`automation_id` that validated and then stalled a tour silently, and its worse
sibling, `window_title_matches` with an empty pattern auto-satisfying on no
evidence. Those are implementation and validation gaps, not brief-authorship
errors, so they do not change the ratio this entry argues from; they belong to
D036's pattern. The milestone total is eleven, not nine.

**Decision.** When dispatching a reviewer, state explicitly that the requirements
brief is a claim to verify, not authority, and that the code should be judged
against the spec and the codebase. Name the controller as the brief's author.
A reviewer told to check work *against* a document will not check the document.

**What it cost to learn.** The wrong-action-feedback milestone produced nine
defects. Not one was visible to inspection — every one came from mutation
testing or review. **Five of the nine originated in the plan or the spec**, both
controller-authored — a majority, and an earlier draft of this entry said four
because it omitted the §7 row below:

| Defect | Consequence had it shipped |
|---|---|
| Tests requiring `SetForegroundWindow` | Could never pass reliably; Windows' foreground lock refuses a non-frontmost process. The task was never green, and a mutation table built on that red baseline recorded a kill that proved nothing. |
| `_wrong_action` read twice in one branch | Two reads of an unlocked slot can disagree, so the message could name a control the user never touched, or pass `None` into a `Callable[[str, str], None]`. **No test could catch it** — the harness's source was a static tuple. |
| Spec §3.5 contradicting spec §3.4 | §3.4 makes the re-hint *be* the OBSERVING transition; §3.5 said the cap still transitions. Both cannot hold. `FLOW.md` faithfully copied the wrong half. |
| Spec §3.3 promising a console line on the satisfied path | The code deliberately does not emit it. The spec was the lone stale document — and the one that calls itself the design of record. |
| Spec §7 deferring native focus events on a 50 ms figure | Wrong by an order of magnitude: 50 ms was the slice interval, not the gap the slicing leaves open, which is 0.18–0.93 s. It was the stated basis for NOT building something, which is the worst place for a wrong number. Listed here as well as in D037 because it is a brief-authorship error by the same test as the other four, and omitting it understated this table's own point. |

Two were caught only because an implementer checked instead of complying: the
`SetForegroundWindow` tests (this milestone), and a dispatch that named the
wrong file for a set of figures on the PREVIOUS milestone — recorded in
`docs/superpowers/ledgers/2026-08-15-perception-tier-2-ocr-ledger.md`. Two
different milestones, cited so the pattern is checkable rather than asserted. An agent that defers to the brief inherits
the brief's errors silently.

**Why the existing rules do not cover this.** D032 requires an independent read
of what the controller authored — and it works, but it is aimed at *documentation
of finished work*, not at the requirements that shaped the work. D034 governs
citations. D018 mutation-verifies behaviour, and a wrong requirement produces
code and tests that agree with each other perfectly. Nothing said the brief
itself is in scope for review.

**The fourth layer data point, reinforcing D036 and D026.** `focus_visited`
recorded RESTING focus rather than focus that MOVED, so a control focus never
left was re-reported on every observation and the loop would have nagged a user
who had done nothing — the exact failure the design forbids. It passed every task-level gate that could have seen it — five of the
milestone's six, since the defect did not exist until Task 2 created it —
including a dedicated review of the perception worker on a more capable model.
"Six" in an earlier draft was the milestone's task count, not the number of
chances this defect had to be caught. At task level the code did precisely what it said: publish
the ids focus visited during this interval. The defect existed only in the
relationship *between* intervals, which no task-scoped review can see.

Worse, the suite certified it: `test_focus_visited_deduplicates` fed a constant
reader and asserted the id was still reported, so the fixture modelled the wrong
property as correct. A test that models the wrong property does not merely fail
to catch a defect — it vouches for it.

This is the fourth instance of D036's generalisation, that **no review layer can
audit its own blind spot**, and the second where whole-branch review caught a
seam every inner gate had passed. Treat that layer as a standing gate, never a
courtesy to skip when everything upstream looks clean.

**Not adopted:** a rule that the controller should not author briefs. Someone has
to, and the alternative — briefs written by an agent with less context — trades a
reviewable error for an unreviewable one. The fix is that the brief gets read
adversarially, not that it gets written by someone else.

**The other half of this rule: implementers must check too, and refusing a
contradicted brief is expected, not initiative.**

Reviewers verifying the brief is necessary but arrives late — after the code is
written to it. The cheaper catch is at execution time, and it has now happened
twice with the same shape: an implementer measured something, found the brief
said otherwise, and followed the measurement.

| Occurrence | What the brief said | What the implementer measured, and did |
|---|---|---|
| Wrong-action, Task 1 | Tests taking real focus via `SetForegroundWindow` | It is refused for a process that is not frontmost. Reported it rather than fighting the environment, which forced the plan's test design to be rewritten. |
| Control bar, Task 4 | Assert `GetForegroundWindow() == bar_hwnd` after opening the panel | The same call is refused under pytest, so that assertion is either always-false here or vacuous elsewhere. Replaced it with a spy asserting the call was ATTEMPTED with the right handle — deterministic and environment-independent — and added a `try/except` around `open_panel`'s own `SetForegroundWindow(hwnd)`, which the brief omitted. §4.4 governs a different call (foreground *restoration* to the target app at close time, Task 5's scope), but states the same accept-once-silently principle, which this guard follows rather than was required by. |

The second is the stronger case: the brief's instruction was not merely
incomplete, it was contradicted by what the implementer could observe, and the
correct response was to deviate and say so loudly in the report.

**So the expectation is stated rather than hoped for.** An implementer that
finds the brief disagreeing with the codebase, an API signature, or a measured
result should follow the evidence, implement what is correct, and report the
deviation prominently — not implement something it has reason to believe is
wrong because the brief said to. A dispatch that says "use this verbatim" means
"do not improve this", never "do not check this".

The controller's job on the other side is to make that safe: name the brief's
known error count in the dispatch, say plainly that it is a claim to verify, and
treat a reported deviation as the process working rather than as an implementer
exceeding its remit.

Related: **D036** (fix the class, not the instance; its layer table gains this as
a fourth row), **D026** (components correct in isolation while the assembly is
not — this applies the same shape to requirements), **D032** (independent read —
necessary, and shown here not to reach the brief), **D018** (mutation-verification,
which cannot see a defect where code and tests agree on a wrong requirement).
# Open-track decisions

* Planner statuses distinguish supported plans, unavailable recipes, invalid
  model output, and deterministic fallback.
* SPACE confirmation is accepted only when the target HWND is the foreground
  window; focus on the bar or another application cannot advance a step.
* The synthetic export application is deterministic and exposes wrong-action
  feedback plus an application-owned completion status.

## D039 — Perception health distinguishes slow work from a stalled worker

**Decision.** Perception health uses worker progress, not observation staleness
alone. A worker with no completed iteration for about **2 seconds** is logged as
`SLOW` but is not restarted. At **12 seconds** without a completed iteration, a
living worker is treated as stalled and restarted once. An exited worker is
detected immediately. The stage name, generation, elapsed age, and heartbeat
are included in every health transition and restart message.

The first restart preserves the existing guided-tour object, recipe, step,
state, and hint decision. It replaces only the perception worker. Observations
from the retired generation cannot publish after restart, and the replacement
must publish a fresh observation before it can affect grounding. If the
replacement also fails its budget, the tour ends with an explicit perception
failure.

**Why.** Complex real application UIA trees can legitimately take longer than
one ordinary tick. Treating a short slow walk as a dead worker causes needless
restarts and can create competing workers. Conversely, a worker blocked inside
one UIA call must remain diagnosable and bounded. Generation-aware progress
keeps the UI thread responsive while making the recovery policy observable.

**Evidence.** `tests/test_worker_health.py` covers slow classification, stage
logging, restart budgets, and one-restart-only behaviour. The existing
perception-service tests continue to pass; the focused Step 1 run was **30
tests passed**. The 2-second diagnostic and 12-second restart thresholds are
implementation policy for this milestone and should be re-measured against
real VS Code before being changed.

Related: **D021** (worker thread protects ESC and the overlay), **D022** (single
observation slot), **D026** (time-based behaviour needs sequence tests),
**D031** (the invariant must imply the safety property), **D034** (measured
figures require a source).

## D040 — Application packs are strict local trust boundaries

**Decision.** Application packs are loaded from local manifests with a strict
schema. Unknown fields, missing fields, invalid regexes, unsafe paths, and
symlinked manifests or recipe directories are rejected. Recipe files are
resolved beneath the pack's trusted `recipes` root and are validated by the
existing `Recipe` schema before the pack becomes available. The registry can
match a foreground identity using executable name and title pattern, but it
does not execute anything and does not accept model-supplied paths.

The initial registry contains Synthetic Export, Notepad, and a VS Code pack
placeholder. The VS Code pack has no executable intent yet; its first workflow
is added only after the registry foundation is independently verified.

**Why.** The planner and future installer need a stable application boundary,
but an application pack is untrusted input until its metadata and recipes have
passed the same path and schema checks as the existing trusted registry. Strict
unknown-field rejection catches pack-format drift early. Matching requires both
declared executable and title identity when both are present, preventing a
shared host such as `python.exe` from matching unrelated windows.

**Evidence.** `tests/test_packs.py` covers built-in pack loading, recipe lookup,
executable/title matching, unknown fields, invalid regexes, and outside recipe
directories. The focused Step 2 run passed **35 tests** including the complete
Step 1 worker-health/perception set.

Related: **D006** (no autonomous input), **D012** (ground live controls),
**D018** (mutation-verifiable safety), **D031** (real invariant rather than a
correlated check), **D032** (independent documentation review).

## D041 — VS Code open-folder verification is user-driven and title-based

**Target selection in this decision is superseded by D047.** Title-based
post-action verification remains current.

**Decision.** The first real application recipe points at VS Code's `File`
menu and instructs the user to choose `Open Folder…` in the native Windows
folder dialog. GhostCursor does not automate inside that dialog. Verification
starts only after evidence of a user action and has a **20-second** timeout.

Verification accepts VS Code title variants such as
`<foldername> - Visual Studio Code` and `<workspace> - Code`. Folder matching
uses case-insensitive Unicode `casefold()` and collapses whitespace. If the
goal contains a path, the final segment is extracted before normalization:
`C:\\Projects\\VSCode-Project` becomes `vscode-project`, and
`/home/user/my app` becomes `my app`. Punctuation remains significant. Empty
or one-character results skip substring matching and use the safer fallback:
the title must be a valid VS Code workspace title and must have changed from
the pre-action title.

**Why.** The native dialog is a separate window/process surface and is not the
right place to expand autonomous control. The title is application-owned world
state, while the user remains responsible for selecting the folder. Starting
the timeout only after an observable action avoids failing while the user is
still deciding what to do.

**Evidence.** `ghostcursor/reasoning/vscode.py` and
`tests/test_vscode.py` cover case and whitespace normalization, Windows and
POSIX-style full paths, degenerate references, title variants, wrong-folder
rejection, and the 20-second recipe configuration. The planner and loop tests
also cover `OPEN_FOLDER` routing and bounded post-action failure; the focused
Step 3 implementation run passed **31 tests**. Real VS Code desktop validation
is still a required acceptance gate and has not been claimed by these unit
tests.

Related: **D006** (user acts; GhostCursor points), **D012** (verify world
state), **D026** (ordered time behaviour), **D034** (recorded measurements),
**D040** (trusted app-pack registry).

## D042 — Foreground validation starts as a logging-only daemon

**Decision.** The first foreground integration is a manually launched polling
daemon:

```powershell
py -3.12 -m ghostcursor.daemon
```

It polls the foreground HWND every **0.5 seconds** by default, resolves the
owning executable and title, matches the strict pack registry, and logs
activation/deactivation-relevant changes. It does not create an overlay, open
the control bar, steal focus, launch applications, register Windows startup,
or provide a tray menu.

Unmatched windows are logged as negative validation data with the executable
name, a title summary truncated to **60 characters**, and the failed identity
surface: executable, title, or both. No screen content, document text,
credentials, or other UI data is captured.

**Why.** Negative matching data is the cheapest way to discover real-world
pack gaps before adding startup UX. Separating foreground identity from tour
activation keeps the first real-app validation reversible and avoids coupling
pack matching defects to tray or startup behavior.

**Evidence.** `ghostcursor/daemon.py` and `tests/test_daemon.py` cover pack
activation, duplicate suppression, 60-character miss summaries, and
executable/title failure reasons. The cumulative focused Step 4 run passed
**51 tests**. The 0.5-second interval is the default polling policy, not a
measured latency claim.

Related: **D006** (no autonomous input), **D040** (strict pack boundary),
**D041** (manual real-app workflow), **D034** (record measurements and policy
values honestly).

## D043 — Implementation is complete; real VS Code validation remains a desktop gate

**Decision.** The reduced real-application platform implementation is complete
through worker health, strict packs, VS Code open-folder routing, and the
logging-only foreground watcher. The final acceptance claim is deliberately
split: automated implementation/regression verification is complete, while
the three-consecutive-run VS Code test remains a manual interactive-desktop
gate. The environment confirms VS Code is installed at
`C:\\Users\\user\\AppData\\Local\\Programs\\Microsoft VS Code\\bin\\code.cmd`,
but no VS Code window was active during this verification session.

**Evidence.** The changed and broader non-hung regression set passed **135
tests**. `py -3.12 -m compileall ghostcursor -q` passed, `git diff --check`
passed, and Graphify `update .` completed with **1312 nodes, 3294 edges, and
68 communities**. The documented all-tests command reached the interactive
guided-tour area but could not complete reliably in this session; it was
stopped after hanging there. The known separate hung-window tests were not
run.

The remaining manual command is:

```powershell
code --new-window
py -3.12 -m ghostcursor.run --goal "Open a folder in VS Code" --target "Visual Studio Code" --seconds 120
```

Run it three times with a real folder selection, including one learning run
and one learned-observation reuse run. Record the desktop result before
claiming the full milestone complete.

## D044 — `VS Code` is a first-class deterministic planner alias

**Decision.** Natural-language fallback treats `VS Code`, `VSCode`, and
`Visual Studio Code` as equivalent application aliases for `OPEN_FOLDER`.
The canonical desktop-validation command, `Open a folder in VS Code`, is an
exact strong phrase with rule-derived confidence **0.95**. Goals containing
one of the aliases plus an open action and a folder/path reference remain
known synonyms at **0.85**.

**Why.** The initial implementation recognized `vscode` and
`visual studio code` but omitted the product's common spaced spelling. Its
path-based regression passed accidentally because the fixture folder name
contained `VSCode`, masking the gap. Deterministic fallback must accept the
documented command even when Ollama is unavailable.

**Evidence.** `tests/test_planner.py` now uses a folder name without the
application token, covers the exact documented command, and covers the same
command when model classification raises `TimeoutError`.

## D045 — The first VS Code workflow uses a targeted UIA query

**Superseded by D047.** The bounded-query principle remains current, but the
specific `File` target did not survive the compact-menu desktop test.

**Decision.** A trusted `code.exe` recipe does not enumerate VS Code's entire
Electron accessibility tree. For the current one-workflow pack, perception
uses a provider-side `FindFirst` query for the exact `File` `MenuItem`. If UIA
cannot expose that element, the walk returns an empty successful observation
so the existing OCR tier can attempt the same trusted target. Other
application recipes retain the generic full-tree walker.

Worker progress is set *before* each potentially blocking operation. In
particular, `stage=walk` is published before entering the UIA provider. The
previous ordering left `stage=focus` visible while the following walk was
actually blocked, even though real focus reads had already been moved to a
separate asynchronous sampler.

**Why.** A real VS Code run blocked twice for 12 seconds while marshaling the
full UIA descendant tree. Restarting repeated the same call and could not
recover. The trusted workflow currently needs one known menu target, so
collecting every editor, terminal, extension, and workbench node adds latency
and failure surface without adding useful authority.

**Evidence.** Targeted UIA, provider-failure degradation, app-specific walker
selection, and truthful blocking-stage reporting are covered by focused
tests. The bounded regression run passed **65 tests** (2 targeted UIA tests
plus 63 perception, health, runtime, planner, and VS Code tests). Real desktop
validation remains required.

## D046 — Executable recipes bind target windows by executable and title

**Decision.** When a recipe `app_id` is an executable name, target identity is
the conjunction of the executable basename and the supplied title pattern.
Application identity lookup skips title collisions owned by another process;
the perception service and focus-safety HWND use the same filtered source. If
no matching executable window exists, the run fails before creating the
overlay. VS Code's specialized walker likewise accepts only `Code.exe`
windows.

**Why.** `--target "Visual Studio Code"` was still only a regular-expression
title lookup. A browser tab, terminal, or other window containing those words
could satisfy it even though the trusted pack manifest requires `code.exe`.
That mismatch could produce a healthy worker observing the wrong application
and an honest but confusing “could not read File” grounding failure.

**Evidence.** Tests cover app-identity collision skipping, HWND filtering,
app-specific source selection, and the targeted UIA path; the focused runs
passed **67 tests**. A subsequent eight-second real-desktop smoke run against
`Welcome - Visual Studio Code` resolved the live `File` `MenuItem` and printed
the expected first-step instruction without a worker stall. It did not click
or open a folder, so three complete user-driven runs remain the acceptance
gate.

## D047 — The Welcome-page Open Folder action supersedes the File-menu target

**Decision.** The first trusted VS Code workflow targets the visible
`Open Folder...` action on the Welcome page directly. UIA performs bounded
exact-name queries for the three-dot, Unicode-ellipsis, and unpunctuated name
variants. When VS Code exposes no matching accessibility element, local OCR is
the fallback. OCR capture is executable-bounded to `Code.exe`, matching the
identity, worker, and focus HWND boundary from D046.

Windows OCR emits separate words, so `reassemble()` now creates conservative
same-line candidates when adjacent words have at least 60% vertical overlap
and a horizontal gap no larger than 1.25 times their height. Originals remain
available, merged candidates contain at most three parts, and the grounding
floor remains 95. This recovers `Open` + `Folder...` without weakening target
matching.

**Why.** The validated desktop used VS Code's compact hamburger menu. `File`
was neither visibly rendered nor exposed by UIA, so both UIA and OCR correctly
failed to ground the old recipe. The Welcome page visibly exposed
`Open Folder...`; local OCR read its two words with boxes `(154,463,197,480)`
and `(204,462,264,476)` relative to the window. Pointing directly at that
action is shorter and matches the actual surface.

**Evidence.** Focused OCR, UIA, capture, VS Code, runtime, perception, health,
and planner suites passed **87 tests**. Live executable-bounded capture then
reassembled `Open Folder...` and grounded it at screen rectangle
`(1106,462,1216,480)`. An eight-second real overlay smoke run rendered the
instruction `Click Open Folder… and select the folder in the Windows dialog.`
without a perception stall. Folder selection and title verification still
require three complete user-driven runs.

## D048 — Real VS Code acceptance run 1 of 3 passed

**Result.** On the normal interactive desktop, the natural-language command
`Open a folder in VS Code` was classified by the local model as
`SUPPORTED (0.98)` with intent `OPEN_FOLDER`. The revised recipe displayed
`Click Open Folder… and select the folder in the Windows dialog.` The user
selected a folder, VS Code exposed the opened workspace in Explorer, and
GhostCursor printed `Tour complete.`

This is acceptance run **1 of 3**. It proves the complete path once—model
classification, trusted recipe selection, executable-bounded perception,
OCR grounding, human action, and world-state verification—but does not yet
satisfy the three-consecutive-run gate.

## D049 — Ask expands into a visible middle-right input panel

**Superseded by D050.** The clipping diagnosis and visible-child requirement
remain current; the horizontal geometry does not.

**Decision.** The control bar is anchored to the middle of the virtual
desktop's right edge with a 24px inset. Its compact state remains 520×56px.
Opening Ask resizes and recentres the parent to 520×142px, displays a visible
`Type your goal:` label and 36px-high EDIT control, focuses that control, and
changes Ask to Submit. Closing or submitting destroys both panel controls and
restores the compact middle-right geometry. Stop and Pause remain in the
always-visible top row.

**Why.** The earlier EDIT control began at child `y=56`, exactly below a parent
whose total height was also 56px. Windows correctly clipped the entire child;
only the Submit label changed, making Ask appear to have no place to type. The
bar was also bottom-centred while the validated desktop workflow needs the
control surface at the right-side midpoint.

**Evidence.** Real Win32 tests assert the right-edge and vertical-centre
coordinates, expanded and restored heights, visible label/edit HWNDs, input
containment inside the parent client rectangle, focus attempt, submission,
pause, stop, and teardown. The focused bar/runtime run passed **31 tests**.

## D050 — The control surface is a vertical right rail with a left-expanding Ask card

**Decision.** The compact control surface is a **148×192px vertical rail** at
the middle-right edge. Stop, Pause, and Ask are stacked vertically and the
status area sits below them. Clicking Ask keeps the same right edge and
vertical centre but expands the parent leftward to **520×260px**. A 372px-wide
prompt column appears to the left of the rail with `Type your goal:` and a
large multiline, vertically scrollable EDIT control. Ask changes to Submit;
closing/submitting removes the prompt column and restores the compact rail.

**Why.** The horizontal toolbar did not match the requested floating-assistant
interaction. The supplied reference uses a narrow persistent action rail and
a larger writing surface that opens beside it. Expanding left preserves the
right-edge anchor and keeps Stop/Pause accessible without placing the prompt
over those safety controls.

**Evidence.** Real Win32 tests assert vertical button ordering, fixed right
edge and centre, expanded width/height, multiline and scrollbar styles,
visible label/edit HWNDs, no overlap between prompt and safety rail, compact
restoration, focus attempt, submission, and teardown. Bar plus runtime Ask
integration passed **32 tests**.

## D051 — Real VS Code acceptance run 2 of 3 passed

**Result.** A second consecutive interactive run classified `OPEN_FOLDER` as
`SUPPORTED (0.98)`, grounded `Open Folder...`, displayed the revised
instruction, accepted the user's folder selection, and printed
`Tour complete.` The Explorer showed the opened AIOS workspace afterward.
One additional consecutive successful run remains before the desktop
open-folder gate is complete.

## D052 — Real VS Code open-folder acceptance gate passed 3 of 3

**Result.** The third consecutive normal-desktop run again classified the
natural-language goal as `SUPPORTED (0.98)`, selected the trusted
`OPEN_FOLDER` recipe, grounded and displayed `Open Folder...`, accepted the
user's folder selection, and printed `Tour complete.` The screenshot also
confirms the compact Stop/Pause/Ask controls are stacked vertically at the
middle-right edge and remain available after completion.

The VS Code open-folder workflow has now passed the required **three
consecutive complete runs**. This closes its real-desktop workflow gate. The
expanded Ask prompt and submitted-goal round trip remain a separate visual and
operational check; compact-rail visibility alone does not prove them.

## D053 — The expanded Ask prompt passed real-desktop visual validation

**Result.** On a normal interactive Windows desktop, clicking Ask from the
completed state expanded the control surface leftward at the middle-right
edge. The screenshot confirms the `Type your goal:` label, large multiline
scrollable input, Submit button, status, and always-available Stop/Pause
controls are all visible without overlap or clipping.

This closes the Ask panel's visual-opening and text-entry-surface gate. The
remaining behavioral check is submitting a typed goal and observing the shared
planner start the corresponding trusted tour; panel visibility alone does not
prove that handoff.

## D054 — Ask submission passed the real-desktop trusted-tour handoff gate

**Result.** The user entered and submitted the VS Code open-folder goal from
the expanded Ask card. The existing session launched a fresh trusted
`open a folder in vscode` tour, grounded `Open Folder...`, displayed its
instruction, accepted the user action, and printed `Tour complete.` This
closes the Ask end-to-end behavioral gate.

**Logging decision.** `Ask received: <goal> — <status>` is emitted immediately
after planning and before the nested tour starts. Previously it was emitted
only after `run_tour()` returned, but a completed nested tour intentionally
keeps its control bar alive until the session timeout. That delayed the most
useful demo evidence even though the handoff had already succeeded.

## D055 — Open Track release work is isolated and governed by a hard freeze

**Decision.** Submission work lives on `submission/open-track`. Existing work
is committed by whole-file dominant concern; optional Open Terminal work must
branch from a certified `stable-pre-terminal` tag and remains unmerged unless
it passes 3/3 consecutive desktop runs. Raw hang dumps stay in ignored
`.artifacts/hang-audit/`; sanitized reachability findings belong here.

Feature development ends 30 August at 20:00 IST. Only fresh-clone validation,
documentation, and release-blocking fixes are permitted on 31 August. Code
freezes at end-of-day; 1 September is upload/paste/verify only, and 2 September
is an emergency link/upload/form buffer with no code changes.

**Why.** A dirty tree, mixed desktop tests, and an unbounded host test run are
submission risks that outrank feature breadth. Branch isolation and an
explicit freeze ensure every failure path returns to the already validated
Open Folder workflow instead of creating an unfinished release.

## D056 — HWND discovery is worker-only and test lanes are environment-isolated

**Decision.** After the perception service starts, the control thread never
calls the HWND source. `run_tour()` initializes the focus-arbitration handle to
zero and updates it only from a completed `Observation.target_hwnd`. SPACE and
focus restoration therefore fail closed until the worker has identified the
trusted target. Test ownership is explicit in `tests/conftest.py`: fast
hermetic, interactive Win32/UIA, pixel, and intentionally hung-window lanes.
The three hung modules run one file at a time and never beside another test
session. The two standalone pixel scripts keep their own runners.

**Finding.** Preserved faulthandler dumps showed two distinct causes. One was
product-reachable: `run_tour()` called `target_hwnd_source(title_re)` directly
on the control thread, and Windows enumeration blocked inside
`uia.windows_matching`; this could freeze ESC and the control rail. The other
was harness-only: `test_wrong_action_tour` waited forever on `Queue.get()` after
its background tour exited, while successful wrong-action and warm-up harnesses
left daemon threads parked. The drivers now bound every wait, surface early
thread exit/exception, and join during fixture teardown. Worker-health logging
also resolves its legacy heartbeat fallback without an eagerly evaluated
attribute access.

**Evidence.** The focused harness/health regression set passed 19 tests; the
real-HWND warm-up lane passed 2 tests; the tier-2 timeline and tick ceiling are
green with desktop-independent preconditions. A fresh per-module audit gave
every collected non-hung pytest module a 90-second ceiling. Every module passed
and none timed out; the longest was the real desktop/pixel guided tour at about
63 seconds. Independent D032 review then found that `test_tick_latency.py`
still owned real windows, so it moved from hermetic to interactive; it also
closed constructor-time harness ownership, added a positive integration test
proving a published worker HWND enables foreground-safe SPACE, and found real
control-bar creation leaking through otherwise faked tour tests. An autouse
fixture now disables real bar creation only for unmarked hermetic tests; the
interactive bar suite remains real. The final documented lanes then passed
independently: hermetic **341 tests twice** (20.50s and 20.25s), interactive
53, pytest pixel 3,
standalone pixels 16/16 and 8/8, and the three isolated hung modules 4, 2, and
7. Raw logs remain under ignored `.artifacts/hang-audit/`.

## D057 — Open Terminal is the second validated VS Code workflow

**Decision.** Register `OPEN_TERMINAL` as a second trusted intent in the VS
Code pack. The deterministic planner recognizes exact and synonym forms of
"open/show the terminal in VS Code," and the model may return only the same
registered intent ID. The local recipe remains the sole action authority.

The recipe highlights VS Code's exact `Toggle Panel (Ctrl+J)` accessibility
control as spatial context and instructs the human to press `Ctrl+\``. It does
not synthesize the shortcut. If exact `Terminal Section` is already visible,
the goal completes before any hint is rendered, so guidance cannot undo an
already-correct state. Otherwise completion requires an absent-to-present
`ELEMENT_APPEARS` transition within 20 seconds of the first rendered hint.
Perception remains executable-bounded to `Code.exe` and publishes only those
two reviewed exact Button names for this recipe.

**Rejected alternative.** Clicking Toggle Panel is not a deterministic way to
open the terminal: a real desktop rehearsal restored the previously active
Debug Console and correctly ended with `verification timed out after 20s`.
The documented native terminal shortcut is deterministic, while verification
still judges the resulting application state rather than the method.

**Evidence.** The focused planner, pack, runtime, UIA, and VS Code set passed
**49 tests twice**. The corrected workflow then passed **3 of 3 consecutive
interactive runs** from a confirmed terminal-hidden baseline. Each run used
`MODEL_UNAVAILABLE_FALLBACK (0.95)` while Ollama was unavailable, grounded the
trusted Toggle Panel context, waited for the human shortcut, observed
`Terminal Section`, and printed `Tour complete.` The acceptance record is
`docs/evidence/vscode-open-terminal.md`.

Post-slice regression runs passed **345 hermetic tests** and **55 interactive
Windows/UIA tests**. The first interactive run exposed one stale one-argument
test fake after `perception_walker_for` gained the recipe-intent parameter;
the background exception was surfaced, the fake was updated to the real
contract, its module passed in isolation, and the full lane then passed.

**Independent review correction.** D032 review found that the original
post-action timer could remain unstarted after a no-op keyboard shortcut and
that an already-open terminal had no safe path. `timeout_from_hint` now starts
this recipe's bounded clock at first render; timeout is evaluated before a
late success; and `accept_if_already_present` completes an already-satisfied
`ELEMENT_APPEARS` goal before grounding or rendering. Schema validation limits
and type-checks both options. Injected-clock tests cover no-op timeout, late
appearance rejection, and already-present completion without a hint. The same
review added mutation-sensitive coverage for planner path containment,
`Code.exe` walker binding, runtime intent-to-walker wiring, and the project-wide
D006 ban on input-synthesis calls.

After those corrections, the final regression lanes passed **50 focused**,
**355 hermetic**, and **55 interactive Windows/UIA** tests. Real desktop
validation passed the already-present path once with no instruction rendered,
then passed the corrected hidden-to-visible transition **3 of 3** again. A live
no-op attempt was not counted as timeout evidence because VS Code independently
exposed the desired Terminal Section during the run; the injected-clock test is
the controlled proof that an unchanged state fails at the deadline.

## D058 — A registered model intent is not executable without deterministic grounding

**Finding.** In the live never-fabricate matrix, prewarmed
`qwen3:4b-instruct` classified `Deploy this project to production` as
`EXPORT_DATA (0.98)`. The intent ID was registered and its recipe was valid, so
the old planner returned a launch-eligible synthetic export plan. The probe did
not launch it. An ID allowlist bounded *what* could run but did not prove that
the selected workflow answered the user's goal.

**Decision.** A model-selected intent with an available recipe is executable
only when it equals the deterministic classifier's grounded intent for the
same goal. If the model selects a different executable intent and deterministic
fallback has a candidate, return `INVALID_MODEL_OUTPUT` with only that trusted
fallback plan. If fallback has no candidate, return `UNSUPPORTED_GOAL` with no
intent and no plan. Model-unavailable or malformed-output paths also return
`UNSUPPORTED_GOAL` when fallback cannot classify; fallback statuses are used
only when a fallback plan actually exists. Registered unavailable intents may
still return `KNOWN_INTENT_RECIPE_UNAVAILABLE`, which is non-launching.

**Why.** The model remains meaningful—it chooses and explains an intent—but
cannot attach execution authority to a semantically unrelated goal. This is a
deliberate precision-over-recall boundary: new language broadening must first
be added to reviewed deterministic intent rules instead of arriving as an
unreviewed model-only route.

**Evidence.** The filled 2×2 unsupported-goal matrix and supported controls are
in `docs/evidence/never-fabricate-matrix.md`. Available Qwen now returns
`KNOWN_INTENT_RECIPE_UNAVAILABLE` for create-file and `UNSUPPORTED_GOAL` for
deploy; the unreachable-endpoint condition returns `UNSUPPORTED_GOAL` for
both. Open Folder and Open Terminal remain `SUPPORTED` with Qwen and
`MODEL_UNAVAILABLE_FALLBACK` without it. Focused planner regression passed 17
tests, and the complete hermetic lane passed **361 tests**.

**Honest limitation.** These Electron controls expose no stable AutomationId.
The learning store and focus-based wrong-action feedback intentionally require
non-empty AutomationIds, so this workflow neither persists a learned control
nor claims ID-based wrong-action naming. Repeated runs therefore prove fresh
live grounding and world-state verification, not a cache-reuse path. Weakening
that guard to manufacture learning evidence would violate D006 and D030.

## D059 — Participant value evidence is an informal, fully disclosed novice check

**Decision.** Value evidence targets one user and task: a novice VS Code user
opening a first project folder. The published protocol compares an unassisted
attempt with a GhostCursor-guided attempt under the same 120-second limit. It
records time to the first correct action, time to verified completion, wrong
turns, help requests, completion, and 1–5 confidence before the baseline and
after the guided attempt. Verified completion means the selected neutral
folder is active as the VS Code workspace; the guided attempt must also print
`Tour complete.` Three participants are the complete planned evidence tier,
not evidence of general effectiveness. Two are acceptable only with `n=2`
disclosed; fewer than two means no participant-value claim. Every result,
including failures and timeouts, remains in the table. Names and contact data
never enter the repository.

**Why.** Three consecutive desktop runs prove engineering reliability, not
user value. A small study can provide concrete observed value, but its order
effect and sample size cannot support statistical or causal claims. The
protocol therefore preserves individual observations and states the
limitation instead of converting a buildathon check into research theater.

**Artifact.** `docs/evidence/novice-vscode-study.md` contains the ready-to-send
invitation, amended fixed protocol, empty live results table, measurement
contract, and claim rules. Recruitment is deliberately deferred until eligible
participant contacts or an authorized messaging channel are available; this
is an intentional dependency decision, not an implied completed action.
Results remain blank until real sessions occur.

## D060 — The demo protects live evidence inside a 4:45 budget

**Decision.** The pitch is capped at 4:45. The Open Folder, Ask/Open Terminal,
and never-fabricate refusal segments are protected; problem framing, evidence
narration, and the close are cuttable. Qwen is prewarmed before recording. The
refusal clip is recorded separately, and any code fix affecting captured
behavior requires the relevant tests and clip to be rerun.

**Why.** The Open Track bar asks for a real problem, meaningful AI, a working
product, and evidence of value. The protected sequence shows each directly
without relying on architecture slides or edited claims, while a 15-second
margin below the form's five-minute limit protects upload and editing variance.

**Artifact.** `docs/submission/demo-video-script.md` fixes the timestamps,
commands, protected/cuttable segments, and final review checklist.

## D061 — Model-call hardening is preserved but excluded from the submission release

**Finding.** Schema-constrained Ollama request work was started directly on
`submission/open-track` and reached 27 focused planner/screen-hint tests, but
had not passed the live never-fabricate matrix or complete regression gates.
Focused tests alone do not justify replacing the already certified inference
contract on the release branch.

**Decision.** Tag release commit `15f20cef8d841fdd75145bd0e2493d61a2a90092`
as `submission-pre-model-hardening`. Preserve the partial five-file slice at
commit `304e8e0` on `post-submission/model-durability`, then return the release
branch to the tagged code. The request hardening, model comparisons, trusted
document retrieval, and any fine-tuning remain post-submission work.

**Isolation evidence.** The annotated tag and release HEAD both resolved to
the exact full commit above. Commit-to-tag, staged, and unstaged diffs were
empty; `git status --porcelain` was empty; the deferred
`ghostcursor/inference/ollama.py` module and its request-contract tests were
absent from `submission/open-track`.

**Release recertification.** On the actual tagged release code, the focused
planner/screen-hint controls passed **23 tests** and the complete hermetic lane
passed **361 tests**. The live eight-cell planner matrix passed with Ollama
0.31.1 and `qwen3:4b-instruct` digest
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`:
both unsupported goals remained non-launching in available and unavailable
conditions; Open Folder and Open Terminal were `SUPPORTED` with Qwen and
`MODEL_UNAVAILABLE_FALLBACK` through the unreachable endpoint. The probe never
launched a tour.

**Honest scope.** The submission ships the existing prompt-request format plus
D058 deterministic semantic grounding. It does not claim structured-output,
`think: false`, fixed-seed, or keep-alive hardening; those changes exist only
on the explicitly incomplete post-submission branch.

## D062 — One bounded Ollama adapter owns request transport and metadata

**Finding.** Ollama 0.31.1 accepted a nullable planner schema and Qwen emitted
JSON null in a forced control, but the same model still mapped the unsupported
deployment goal to `CREATE_DOCUMENT (0.8)`. Structured output constrained the
shape without making the decision semantically correct.

**Decision.** Both inference paths will use one non-retrying Ollama adapter for
the request body, HTTP transport, response envelope, and generation metadata.
This slice builds and fixes that adapter; caller migration belongs to D063.
The adapter sends `think: false`, temperature 0, seed 42, a 4096 context, a
15-minute keep-alive, and caller-bounded output. It preserves `done_reason`
and token/time metadata so a length cutoff is not mislabeled as arbitrary
malformed output. Callers remain responsible for strict semantic validation;
D058 remains the execution boundary.

**Evidence.** `docs/evidence/model-durability-task0.md` records the real probe.
`tests/test_ollama_request.py` fixes the shared request and metadata contract.

## D063 — Nullable advice and execution authority are separate contracts

**Decision.** Planner output requires the canonical three fields and permits a
registered intent or JSON null. Null plus a deterministic trusted recipe is
reported honestly as `MODEL_ABSTAINED_FALLBACK`; null without one remains
`UNSUPPORTED_GOAL`. A pure `resolve_model_decision()` function applies D058 so
production and evaluation share the same authority policy. Screen-hint output
is likewise canonical-only and can select only a unique, currently observed
UIA AutomationId whose name is recipe-approved. More than 32 eligible controls,
duplicate IDs, or no eligible IDs skip model inference.

**Why.** Structured generation can prevent invented fields while still making
the wrong semantic choice. Parsing therefore validates substance and the pure
policy—not schema conformance—decides whether a reviewed recipe may execute.
Only eligible controls are disclosed to hint inference, bounding latency and
avoiding unrelated UI text.

**Evidence.** The focused adapter/planner/hint lane passes 41 tests, including
valid abstention, strict alias/extra-field rejection, deterministic mismatch,
duplicate IDs, candidate ceilings, and unavailable-model fallback.

## D064 — Model changes require one versioned, read-only, three-lane gate

**Decision.** Every model name/digest, prompt, schema, parser, adapter, or
planner/hint inference-path change must run the same versioned evaluation set.
The set contains 30 independently drafted semantic cases grouped by
`family_id`: exact supported goals, paraphrases, misspellings, ambiguous goals,
near misses, and adversarial requests. Expected raw labels are human semantic
judgments, never incumbent outputs. Observed Qwen output is baseline evidence,
not ground truth. The dataset cannot produce a trusted baseline until its
metadata says `owner-reviewed`, identifies the reviewer and review date, and
confirms it was frozen before the first complete trusted run.

The standing command has three honest lanes: hermetic policy/contract checks,
bounded localhost Ollama requests, and an explicitly requested interactive UIA
check. Omitting `--interactive` is reported as a skip and cannot close the
milestone. Generated full reports live under ignored `.artifacts/`; reviewed
summaries may be committed separately.

**No-action boundary.** The interactive lane starts and owns one Synthetic
Export child, calls perception and hint inference directly, and never imports
the tour dispatcher. An evaluation-package import allowlist, project AST scan,
the repository-wide D006 input-synthesis scan, runtime `ghostcursor.run` guard,
single approved AutomationId schema, and `STATUS_ID` before/after sentinel are
independent checks. The sentinel proves the Export/Wrong Control status did not
change; it is not an exhaustive UI diff. The combined API-path prohibition,
import/AST checks, runtime guard, and sentinel support the stronger read-only
claim. Third-party dependencies are intentionally not recursively AST-scanned.

**Fixture contract.** The Synthetic Export fixture was captured through real
Windows UIA on 2026-08-25 and records source commit provenance. Name, control
type, AutomationId, and source must match exactly. Geometry is structural only:
four integers, positive area, and intersection with the target window. Focus,
HWND, timestamps, enumeration order, and absolute position are volatile and do
not participate in parity.

**First draft measurement.** The unreviewed Qwen 3 4B draft passed every hard
gate: 100% raw accuracy on six exact supported controls, zero launch-eligible
plans across unsupported cases, safe four-cell never-fabricate results, and
exact Export selection from candidate `1005`. Overall semantic accuracy was
26/30 (86.7%); the model over-committed on `Open it`, `Make a new one`, `Open a
project`, and `Build and publish a website`, all at 0.95 confidence. D058 or an
unavailable recipe prevented authority in every case. Median request latency
was 2861 ms in the complete interactive draft run. This is diagnostic evidence,
not the frozen incumbent baseline, until owner review is recorded.

**Consecutive acceptance.** Final closure requires two consecutive full
non-draft `--interactive` passes. Any product or ambient failure resets the
count to zero; its report is preserved and classified before another attempt.
Two nonconsecutive successes do not satisfy the gate.

## D065 — Raw gate reports stay local; reviewed summaries carry claims

**Decision.** Timestamped gate JSON remains ignored under
`.artifacts/model-evaluation`. A concise committed evidence artifact records the
tested Ollama version, manifest digest, dataset review state, hard gates,
category metrics, semantic failures, latency, interactive fixture result, and
known limits. A draft summary must say it is not the incumbent baseline. It is
promoted only after label review and the two-consecutive-pass rule in D064.

**Why.** Full per-request reports are useful diagnostics but noisy and can be
regenerated. Committing only an interpreted summary keeps repository evidence
reviewable without allowing a cherry-picked report to erase a failed attempt
or an incomplete review gate. The source report paths remain named so local
diagnosis retains provenance.

**Evidence.** `docs/evidence/model-durability-draft.md` records the first
complete interactive draft, including the rejected stale-window attempt, the
26/30 raw result, all four over-commitments, zero launch-eligible unsupported
plans, exact model digest, and the scoped no-action claim.

## D066 — Dataset 1.0.0 is owner-reviewed and frozen before baseline

**Decision.** Project owner Arrnnnvva reviewed all 30 semantic labels and
approved them with two conditions. The four misspelling predictions were run
directly through the current deterministic classifier before freeze: `Exprot`,
`floder`, and `Opne` returned no trusted intent; `Open the intergrated terminal
in VS Code` returned `OPEN_TERMINAL`. Dataset metadata now records version
1.0.0, owner role, review date, and `frozen_before_first_full_baseline_run:
true`. The first trusted full baseline must run strictly after this commit.

**Why the misspelling asymmetry is deliberate.** The classifier is not fuzzy.
Its VS Code terminal synonym requires `open` or `show`, `terminal`, and a VS
Code alias; misspelling the unused word `integrated` leaves every required
anchor intact. `Exprot` removes the required export/save/download verb,
`floder` removes the folder-or-path anchor, and `Opne` removes the open/show
verb. These labels are therefore measurements of the current deterministic
contract, while `expected_raw_intent` remains an independent semantic label.

**Prior exposure disclosure.** Three exact supported controls, the deployment
confusion case, and the near-open-project probe had individual exposure before
the full dataset was drafted. Their `previously_probed` flags and the dataset
review metadata preserve that fact; exact-control accuracy is not described as
independent blind evidence.

## D067 — Qwen 3 4B is the accepted frozen incumbent at 26/30

**Decision.** Dataset 1.0.0 and the unchanged request contract passed two
consecutive complete non-draft `--interactive` gates after freeze commit
`93047ea`. Qwen achieved 26/30 (86.7%) raw semantic accuracy and 6/6 exact
supported accuracy in both runs. All hard gates passed: zero unsupported
launch-eligible plans, safe available/unavailable matrix, supported controls,
exact synthetic and live Export selection, no exact length truncation, zero
tour dispatch, and unchanged status sentinel. This manifest digest is now the
incumbent and immediate rollback target.

**Observed limitation.** The model repeated four 0.95-confidence
over-commitments in both runs: `Open it` to `OPEN_FOLDER`, `Make a new one` to
`CREATE_DOCUMENT`, `Open a project` to `OPEN_FOLDER`, and `Build and publish a
website` to `CREATE_DOCUMENT`. D058 or recipe unavailability denied authority
in every case. Schema validity is therefore reported as zero parse failures,
not evidence of semantic caution.

**Evidence.** The accepted reports are
`.artifacts/model-evaluation/model-gate-20260825-181341.json` and
`model-gate-20260825-181618.json`; raw reports remain ignored.
`docs/evidence/model-durability-baseline.md` is the committed reviewed summary.
Pass medians were 2870 ms and 2771 ms. Pass 1's 10,671 ms maximum is an
observed session value, not a formal cold-start benchmark.
