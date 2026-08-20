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

**The pattern this is the third instance of.** Each review layer catches a class
of defect the layer inside it cannot see, by construction:

| Layer | What it caught that the inner layer structurally could not |
|---|---|
| Whole-branch review | A standing tier-2 request never retracted across a window change — an interaction between three tasks each individually correct and each individually reviewed as correct. Task-scoped review cannot see a seam. |
| Controller mutation | A tick-loop test that passed with the warm-up gate deleted from `run.py`. Five green stability runs, a docstring explicitly claiming non-triviality, and a passing suite all missed it. Only mutating the GATE — not re-running the test — exposed it. |
| Outside review (PR) | The sibling docstring above, in a fix the whole-branch review had itself produced and closed. |

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
failure this whole loop exists to avoid. Focus changes because a user acted
on a control; it does not drift on its own the way the element set does.

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
  already recorded at D028) — design spec §2.3.

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
real contiguous blind window is **0.18–0.93s** (walk plus tier 2), covering
roughly **18–53%** of wall time against the 0.2s sampled interval — a
wrong-then-right round trip landing inside that window is well within normal
human click speed, not faster than it (design spec §7, corrected during this
milestone; the corrected figure is itself the kind of number D034 exists to
keep honest). The deferral still stands, but for the real reason: native
events arrive as COM callbacks on RPC-managed threads and would need
marshalling into the worker's apartment — exactly the D021 area this project
has already paid to avoid, not because the gap is negligible.

**`FOCUS_MOVES_TO`.** The verification kind that had always raised
`NotImplementedError` because focus was never tracked is enabled by this
milestone, with its own tests, rather than riding in silently on a feature
that merely happened to unblock it.

Related: **D021** (only primitives cross the worker/UI thread boundary),
**D027** (one write per tick — why the re-hint reuses `OBSERVING`), **D028**
(the worker-perceives / loop-decides split, applied a second time), **D034**
(every number above named to its record; the §7 correction is this rule
applied to the project's own prior draft).
