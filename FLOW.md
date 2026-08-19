# FLOW.md

How execution actually travels between files, functions, and modules — what calls
what, in what order. Updated as the codebase grows. The "you are here" marker at
the bottom shows exactly what's being built/modified right now.

---

## Current milestone: Perception tier 2 (OCR)  ✅ built — see "You are here"

## Previous milestone: Intermediate Project — Single-App Guided Tour  ✅ complete

The Beginner milestone (Static Hint Overlay ✅) is complete. The Intermediate
milestone builds the observe-act-verify state machine, the grounding ladder,
live UIA verification, and the recipe-driven guided tour interface.

Previous milestone (Beginner) goal: a Win32 layered window that draws a ring
around one UI element found via `pywinauto`, drawn with GDI, refreshed on a
timer. No AI, no reasoning loop.

### Import-time ordering (matters — see D010)

```
ghostcursor.run
  imports ghostcursor.overlay.window
      imports ghostcursor.overlay.dpi
          dpi._ensure_dpi_awareness()      <-- runs AT IMPORT, before any window
              SetProcessDpiAwarenessContext(-4)   -> 0 (fails on this machine)
              SetProcessDPIAware()                -> 1 (works; 1536x864 -> 1920x1080)
```

Nothing may query DPI-dependent state before this, and nothing may create a
window before it either — awareness locks permanently on first use, and
`mss` flips it implicitly if it gets there first.

### Runtime call graph (as built)

```
run.main()
  window.create_overlay_window()
      dpi.virtual_screen_rect()            -> (0, 0, 1920, 1080)
      RegisterClass(GhostCursorOverlay)    (once; brush kept at module scope)
      CreateWindowEx(WS_EX_LAYERED | WS_EX_TRANSPARENT
                     | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
      SetLayeredWindowAttributes(colorkey=magenta, LWA_COLORKEY)
      ShowWindow(SW_SHOWNOACTIVATE)        (never steals focus)

  loop every REFRESH_SECONDS (0.25s), until ESC or --seconds:
      run.escape_pressed()                 GetAsyncKeyState(VK_ESCAPE)
      run.resolve_target(title_re, control)
          perception.uia.find_element()    UIA descendants, name match
              -> None for Notepad "Save" (it lives in a menu, not a button)
          perception.uia.window_bbox()     UIA top-level rect  -> (160,160,1009,945)
              falls back to uia._raw_window_rect() only if UIA gives nothing
          -> centre point of that rect
      window.set_hint(hwnd, x, y)
          stores _hint (screen -> client coords via _origin)
          InvalidateRect + UpdateWindow    -> synchronous WM_PAINT
      window.pump_messages_nonblocking()

  window._wnd_proc  on WM_PAINT:           <-- the ONLY place anything is drawn
      BeginPaint
      FillRect(client rect, colorkey brush)    entire overlay -> transparent
      _paint_ring(hdc, x, y, radius)           only if a hint is set
      EndPaint
  window._wnd_proc  on WM_ERASEBKGND: return 1   (we erase in WM_PAINT)

  finally:
      window.destroy_overlay_window(hwnd)
```

### Files
| File | Role |
|---|---|
| `ghostcursor/run.py` | entry point, timer loop, ESC/timeout safety, arg parsing, grounder builder for live promotion |
| `ghostcursor/overlay/dpi.py` | declares DPI awareness at import; one coordinate space |
| `ghostcursor/overlay/window.py` | layered click-through window, WM_PAINT rendering |
| `ghostcursor/perception/uia.py` | UIA element/window lookup + raw win32 fallback |
| `ghostcursor/reasoning/schema.py` | frozen data structures: Recipe, Step, VerificationRule, enums (UserAction, VerificationKind, Risk) |
| `ghostcursor/reasoning/grounding.py` | turn step descriptions into live screen rectangles via the 4-rung matching ladder (id, type+exact name, UIA-only substring, OCR fuzzy at floor 95) + promotion |
| `ghostcursor/reasoning/verification.py` | check world state to decide if user completed a step |
| `ghostcursor/reasoning/loop.py` | observe-act-verify state machine (IDLE → OBSERVING → DECIDING → RENDERING_HINT → AWAITING_USER_ACTION → VERIFYING) |
| `ghostcursor/reasoning/renderer.py` | adapt loop's Renderer protocol onto the Win32 overlay |
| `ghostcursor/reasoning/recipes/synthetic_export.json` | hand-authored recipe for the synthetic test app |
| `ghostcursor/perception/appinfo.py` | identifies the app owning a window (HWND -> PID -> exe path -> file/Appx version) for version-scoped observation lookup |
| `ghostcursor/reasoning/identity.py` | `step_key()` — durable hash of intent + claimed descriptor, the key observations are stored/retrieved under |
| `ghostcursor/memory/store.py` | `ObservationStore` — local SQLite knowledge base of learned observations, keyed by `(step_key, app_id, app_version, automation_id)` |
| `ghostcursor/perception/service.py` | `PerceptionService` — runs the UI-tree walk AND tier 2 on a worker thread that owns its COM apartment, publishes one timestamped `Observation` into a single overwritten slot, and receives the UI thread's `Tier2Request` through a second overwritten slot going the other way |
| `ghostcursor/perception/health.py` | `WorkerHealth.check()` — notices a dead or stalled worker, restarts it exactly once, then ends the tour with a reason |
| `ghostcursor/reasoning/staleness.py` | `StalenessLadder` — how old the last confirmed-fresh walk is, as `Freshness.FRESH / DIMMED / INFERRED / HIDDEN`, with debounced recovery; `display_freshness()` combines age with provenance |
| `ghostcursor/perception/ocr.py` | `WindowsOcr` wrapper over `Windows.Media.Ocr`, `ocr_available()`, and `reassemble()` for labels that wrap onto two lines |
| `ghostcursor/perception/capture.py` | DPI-correct per-window pixel capture and frame differencing |
| `ghostcursor/perception/tier2.py` | `Tier2Controller` — when OCR runs and when it stops: per-step stickiness, a 1.0s floor, a ceiling of 20 CONSECUTIVE FRUITLESS reads (reset by `grounded()`), terminal exhaustion. Owned by the perception worker, never called from the UI thread |
| `tests/backdrop.py` | controlled solid-colour window used as a test surface |
| `tests/hung_window.py` | child process that creates a window and then stops pumping messages — reproduces the 41s UIA block deterministically |
| `tests/test_hung_window.py` | `HungWindow` context manager + the block measurement; the fixture Tasks 5-7 are built on |
| `tests/test_run_threaded.py` | ESC stays responsive while the target is hung — the property this whole design exists for |
| `tests/test_freshness_timeline.py` | the staleness ladder as an ordered sequence inside a real `run_tour`, on an injected clock (D026); carries the two composition bugs as named regressions |
| `tests/test_tier2_controller.py` | the cadence itself: the 1.0s floor, the frame diff, the fruitless-run ceiling and its reset, all on an injected clock |
| `tests/test_tier2_timeline.py` | tier 2 end to end as an ordered sequence — UIA-blind service, request slot, OCR elements arriving on a later observation, amber ring |
| `tests/test_tier2_tick_ceiling.py` | D020's 0.5s tick ceiling measured WHILE tier 2 is engaged — the case `test_tick_latency.py` cannot reach, because there grounding never fails |
| `tests/test_grounding_rung4.py` | rung 4 at floor 95, and the guard that stops rung 3 bypassing it; fixtures are real spike reads with their real scores |
| `tests/test_ocr_engine.py` | the `Windows.Media.Ocr` wrapper, and that unavailability degrades instead of raising |
| `tests/test_ocr_reassembly.py` | `reassemble()` on the spike's real wrapped-label reads — rejoining without inventing new labels |
| `tests/test_capture.py` | per-window capture and `frames_differ` — the diff is what stops OCR running every tick |
| `tests/test_element_source.py` | `Element.source` — how the system tells a pixel guess from a confirmed control |
| `tests/test_freshness_inferred.py` | `display_freshness` — INFERRED, its precedence, and the fail-safe for unrecognised sources |
| `tests/test_overlay_inferred.py` | the third ring colour is distinguishable from the other two, in pixels |
| `tests/test_overlay_freshness.py` | the dimmed ring colour differs from the fresh one |
| `tests/test_first_paint.py` | a standing property (D027): a hint's FIRST paint already carries its final display state, over the whole `Freshness` x source cross-product |
| `tests/test_regression_ocr_fixes.py` | the three properties c6115a1 left unguarded: the laundering sequence, the churning page, and the promotion source guard |
| `tests/test_overlay.py` | 16 checks: styles, click-through, transparency, hint placement, dimmed AND inferred ring colours, stale pixels, teardown |
| `tests/test_end_to_end.py` | 8 checks: perception -> coordinate -> ring lands on the window, off-screen rejection |
| `tests/uia_app.py` | real Win32 window with known AutomationIds, used as deterministic grounding target |
| `ghostcursor/inference/` | empty; later milestones |

**A hung window is a desktop-wide side effect.** Any UIA enumeration that
touches a non-pumping window pays the SendMessage timeout, no matter which
process started the walk. Measured: the same two test files take **6.28s
normally and 100.13s** while a hung window sits on the desktop. So the three
hung-window files above must never run concurrently with another test
session, and `HungWindow` must reap its child unconditionally — a fixture
that outlives its test turns that 16x tax permanent. Two "flaky" failures in
this repo were exactly this and nothing else.

### Verification status
```
python -m tests.test_overlay         16/16 pass
python -m tests.test_end_to_end       8/8  pass
python -m pytest tests/ (fast)      280 passed in 22s   excludes the three slow files below
python -m pytest tests/test_run_threaded.py \
                tests/test_perception_service_hung.py \
                tests/test_hung_window.py            13 passed in 128s
```
The first two (pixel harnesses) have their own runner and are not collected by
pytest. The three files in the second group each park a real non-pumping
window on the desktop, which is why they are slow and why they must not run
concurrently with anything else — see the note under Files. Also confirmed against a real Notepad window: 440 ring pixels, 49x49
diameter, centroid within 1px of the requested coordinate. And confirmed
against a real persistence run: a UI AutomationId learned by one process was
reused by a completely separate later process (rung 2 -> rung 1 across
process boundaries), and deleting the database file returned behaviour to
rung 2 — see the persistence call graph above.

### You are here
**Perception tier 2 (OCR) is built** (D028-D030). When UIA cannot see the
control a step names, the screen is read with `Windows.Media.Ocr` and the
hint renders amber (`INFERRED`) rather than cyan, so a pixel guess never
wears the confirmed-control ring.

**OCR runs on the perception worker, not on the tick.** The UI thread is the
only one that knows which step is current and whether grounding just failed,
so it DECIDES and REQUESTS — `service.request_tier2(step)`, a lock-and-assign
into a second overwritten slot running the opposite way to the observation
slot. The worker EXECUTES (capture, diff, OCR, reassembly) and publishes what
it read as `ocr_elements` on a LATER observation, tagged with `tier2_step` so
one step's reads can never be mistaken for another's. There is no wait, no
join and no future: grounding may simply fail for a tick or two until the read
lands, which the 10s grounding grace and the staleness ladder already cover.
There is no `wanted` flag either — the ABSENCE of a request is "not wanted" —
so the UI thread cancels when UIA answered (`cancel_tier2(i)`) and at every
step boundary (`cancel_tier2()`), or a request from a step nobody is on keeps
costing 0.14-0.23s of worker time as often as the 1.0s floor allows.

What forced it, measured on real screens: Adobe Acrobat exposes **0 of 16**
tool labels to UIA — 20 elements, 17 of them anonymous Panes — while OCR reads
**21 of 24** labels at the shipped floor of 95. A floor of 85 was rejected, but
not for anything on this Acrobat screen: the binding case was Canva Home,
where `Uploads` scored 92.3 against a read of `upload` — two different real
Canva surfaces one character apart. The Canva photo editor exposes
**4 of 13** even with a fully warm Chromium accessibility tree.

What it deliberately does NOT cover: Electron apps are *blind-until-asked*,
not blind — Chromium enables its accessibility tree on demand, and the first
UIA probe switches it on. They want a **warm-up retry**, which is cheaper
than OCR and is its own separate milestone. Icon-only controls carry no text
and are unreachable by any OCR; that is tier 3, the VLM.

Photoshop itself was never measured. Acrobat was a proxy for its shape.

Two bugs found only where the pieces compose, both fixed and both now
guarded by tests: an OCR hint was painted once in confirmed-control cyan
before being corrected in the same tick (D027 — any two-step render where
paint can interleave with correction is a laundering bug); and an
unrecognised `source` resolved to the most trusting label, which a future
VLM tier would have walked straight into.

Previously: perception moved **off the UI thread** (D021-D024). The escapability
guarantee is structural rather than test-enforced: a hung target can no
longer block the tick loop, so ESC keeps being polled no matter how slow
perception becomes. Proven by driving the real `run_tour` against a real
hung window; making perception synchronous again fails that test with
`ESC was only polled 7 times before run_tour returned`, and the run takes
95.6s instead of 16s.

What that milestone added: a worker thread owning its COM apartment
(`service.py`), a single timestamped slot, the staleness ladder
(`staleness.py`) and its dimmed ring, worker-death detection with
restart-once (`health.py`), and the freshness gate that keeps
`AWAITING_USER_ACTION` from verifying against an observation no newer than
the one `OBSERVING` used.

Two bugs found only where those pieces compose, both fixed:
- a dead worker used to be reported as `cannot find 'Export' on screen`,
  because the 10s grounding grace expired before the 15s health budget —
  pointing the user at their own application instead of at ours;
- "restart once, then give up" degenerated into "give up", because the
  staleness clock measures observations, not workers, so a replacement
  inherited the staleness of the worker it replaced and died 0.25s later.

The Intermediate milestone (Single-App Guided Tour) remains **COMPLETE** —
verified end-to-end on a real, non-synthetic application, not only the test
harness.

Closing evidence, a guided tour run twice against live Notepad (a Store app,
`notepad.exe` 11.2606.15.0 resolved through the Appx package path, 39 UIA
elements):

```
run 1   hydrated=0   rung 2 (matched by name)          learned AutomationId 'AddButton'
run 2   hydrated=1   rung 1 (matched by that id)       same target, no re-learning
both    state = AWAITING_USER_ACTION                   dwelling for the human, never acting
both    440 ring pixels landed on the real button      observe -> hint 147-161 ms
```

The tour stopping at AWAITING_USER_ACTION is the design, not a failure: the
system draws a hint and waits. Only the user can advance the step (D006).

The
`IDLE → OBSERVING → DECIDING → RENDERING_HINT → AWAITING_USER_ACTION →
VERIFYING` state machine, the grounding ladder, live UIA verification, the
Win32 renderer adapter, the `run.py --recipe` entry point, and now
persistence — promotion survives process exit via `ObservationStore`, keyed
by `(step_key, app_id, app_version, automation_id)`, hydrated before each
tour and written on every promotion — are all built and wired together
end-to-end, and so is perception tier 2 (OCR). What remains unbuilt is the
doc-ingestion knowledge base — web search, doc ingestion, embeddings, intent
matching, recipe distillation — and tier 3, the VLM (spec sections outside
9-10).

### Runtime call graph — guided tour (as built)

```
run.main()
  run.run_tour(recipe_path, title_re, seconds)
      schema.Recipe.load(recipe_path)

      --- perception moves OFF this thread, before the overlay exists ---
      tier2.build_controller(clock)    -> Tier2Controller | None (None = no OCR here)
                                          built on THIS thread, then HANDED OVER and
                                          never touched from here again
      service.PerceptionService(title_re, tier2=controller).start()
          worker thread: CoInitializeEx, then forever:
              uia.iter_elements(title_re)                  ~40s against a hung target
              verification.take_snapshot(..., observed_at)  timestamped from the service clock
              service._tier2_payload()                     OUTSIDE the walk's try, so a raising
                                                           walker cannot skip the OCR run itself
                                                           — but publication only happens after
                                                           the walk succeeds, so on a raising
                                                           walk OCR still runs (spending the
                                                           one-shot `grounded` flag) and its
                                                           result is simply discarded, unpublished
                  _take_tier2_request()                    consumes `grounded`; the request
                                                           itself STANDS until cancelled
                  tier2.Tier2Controller.elements_for(step, title_re)
                      capture.capture_window()      per-window pixels, DPI-correct
                      capture.frames_differ()       skip if nothing visibly changed
                      ocr.WindowsOcr.read()         word-level reads, frame-relative
                      ocr.reassemble()              rejoin labels that wrapped
                      -> Elements with source="ocr", window origin ADDED
              -> publishes ONE Observation into a slot (overwrite; no queue, no history),
                 carrying snapshot + UIA elements + ocr_elements + tier2_step/_engaged/
                 _exhausted/_max_runs. `tier2_step` is -1 when tier 2 did not run
      staleness.StalenessLadder()      how old the last CONFIRMED-FRESH walk is
      health.WorkerHealth(service, ladder)   restart once, then end the tour

      window.create_overlay_window()
      GuidedTour(recipe, grounder=run.grounder_from_slot, snapshotter=run.snapshotter,
                 verifier=verification.verify, renderer=OverlayRenderer(hwnd))

          run.snapshotter()          service.latest() -> Observation | None
                                     None -> empty Snapshot (observed_at 0.0, reads as FRESH)
                                     ladder.observed() ONLY when observed_at ADVANCES —
                                     re-reading the same slot must not reset the clock
          run.grounder_from_slot()   uses the elements the LOOP passed in (the ones OBSERVING
                                     snapshotted), so OBSERVING and DECIDING describe the SAME
                                     instant (D019); falls back to service.latest() only when
                                     the loop passes none. Grounds the LAST observation, so a
                                     merely-stale slot keeps succeeding and the loop's
                                     grounding grace never starts

                                     --- TIER 2, only if that grounding FAILED (D028) ---
                                     UIA answered? service.cancel_tier2(i) and return — a
                                     standing request is a standing cost on the worker.
                                     Otherwise:
                                     service.request_tier2(i)   lock-and-assign, never blocks.
                                         The READ happens on the worker; its result turns up
                                         in a LATER observation, so this tick may still fail
                                         to ground (grace + staleness ladder cover that).
                                     ocr_elements = observation.ocr_elements, but ONLY if
                                         observation.tier2_step == i — flags and reads describe
                                         ONE step, and they come from the SAME observation
                                         OBSERVING snapshotted (D019)
                                     re-ground with UIA elements + OCR elements. Rung 3 excludes
                                     OCR; OCR gets in at rung 4 (fuzzy, floor 95) and at rung 2
                                     (byte-exact name — a strictly higher bar).
                                     grounded? service.report_tier2_grounded(i) — a productive
                                     read must not spend the step's budget.
                                     Stickiness is per STEP; 1.0s floor, ceiling of 20
                                     CONSECUTIVE FRUITLESS reads; hitting it ends the step
                                     rather than freezing the hint.

      loop every REFRESH_SECONDS (0.25s), until ESC, --seconds, DONE, FAILED, or health:
          run.escape_pressed()                 GetAsyncKeyState(VK_ESCAPE) — never blocked now
          tour.step_index changed?              service.cancel_tier2() — the worker cannot see
                                                a step boundary, and nothing else ends a standing
                                                request, so a step that asked and was then LEFT
                                                would keep the worker reading for it forever
                                                (AWAITING_USER_ACTION dwells for many ticks
                                                without ever calling the grounder)
          GetAsyncKeyState(VK_SPACE)            polled -> tour.confirm() for user_confirms steps
          health.check()                        once per tick; suppressed until the first
                                                observation lands or dead_after_s from tour start
                                                (ladder.age() is inf before then)
          service.latest() is None?             SKIP the tick entirely (still pumps + polls ESC).
                                                Spec §9: stay in OBSERVING. Ticking here would
                                                let the empty placeholder snapshot become a
                                                VERIFICATION BASELINE and mark a step complete
                                                the user never performed (D006)
          tour.tick()                           _advance() then renderer.settle() — the loop
                                                closes its own tick so a driver cannot forget,
                                                and AWAITING's early return cannot skip it
              OverlayRenderer resolves the AGE half of the display state ONCE per tick
                  freshness_source() -> run.current_display_freshness() -> ladder.freshness()
                                        (a MUTATING query: exactly one call per tick; None
                                         resolves to INFERRED, never to FRESH)
                  the SOURCE half is NOT read here. `show()` binds the target's provenance
                  into a frozen `_Hint(centre, source)`, and `_paint()` folds it in with
                  staleness.display_freshness(freshness, hint.source) — so a repaint
                  reproduces the state ITS hint was created with, never a later step's.
                  There is no `grounded_source` variable any more: a provenance that could
                  be updated separately from its coordinate is exactly what let DECIDING
                  repaint the previous step's OCR centre in confirmed cyan for a whole tick.
                  -> exactly one set_hint/clear_hint emission per tick, so no WM_PAINT can
                     observe a provisional state and launder a pixel guess into FRESH (D027)
              [DECIDING]    grounder(step, i, elements)
                                grounding.ground(step, title_re, elements=obs.elements)
                                                                    rung 1: automation_id
                                                                    rung 2: control_type+name
                                                                    rung 3: substring/synonyms,
                                                                            source=="uia" ONLY
                                                                    rung 4: OCR text, fuzzy,
                                                                            floor 95
                                grounding.promote(step, grounded, app_version, locale=ui_locale)
                                  (writes automation_id back to in-memory Step; persists to disk.
                                   Refuses anything whose source is not "uia" — D030)
                                -> GroundedTarget | None  (None => clear hint, 10s grounding
                                   grace, then FAILED; never a guessed coordinate.
                                   Only reachable once a real observation exists — the tick
                                   loop skips entirely until then — so a grounding failure
                                   means perception WORKS and the element is genuinely absent.
                                   run.read_failure_reason(step, i) replaces the generic
                                   "cannot find X" when the published observation says tier 2
                                   was engaged for THIS step — reading `tier2_engaged` /
                                   `tier2_exhausted` off the slot, never off the controller,
                                   which the worker owns)
              [RENDERING_HINT]  OverlayRenderer.show(grounded, instruction_text)
                                    window.set_hint(hwnd, centre-of-bbox)
                                    .last_instruction = instruction_text   <-- run.py dedupes prints on this
              [AWAITING_USER_ACTION]  run.snapshotter()   (this is "after")
                                       loop._is_newer(after, before) — a slot that has not
                                       advanced is NO verification attempt, not a failed one
                                       verification.verify(rule, before, after)
                                           world-state check, not method (D014)
              [VERIFYING]   step_index += 1; renderer.clear(); back to OBSERVING
          ladder.freshness()                    applied AFTER the DONE/FAILED breaks:
              HIDDEN  -> window.clear_hint(hwnd)      (never passed to set_hint: _paint_ring
                                                       treats everything-not-FRESH as dimmed)
              DIMMED/FRESH -> window.set_hint(..., freshness=)  only while the renderer is
                                                       still showing something
          run.py prints "step N: <instruction>" only when it changed since the last tick
          window.pump_messages_nonblocking()

  finally:
      window.destroy_overlay_window(hwnd)   always runs, even on exception
      service.stop()                        before the store closes
```

### Runtime call graph — persistence (as built)

Promotion now survives process exit. Before a tour is constructed, the recipe
is hydrated from disk; while it runs, every promotion is written back to disk
immediately, so a second, later process reading the same app reuses what the
first one learned instead of re-discovering it from name matching.

```
run.run_tour(recipe_path, title_re, seconds)
    schema.Recipe.load(recipe_path)
    window.create_overlay_window()
    appinfo.app_info_for_window(title_re)       -> AppInfo(app_id, exe_path, version, kind)
                                                    HWND -> PID -> exe path -> file/Appx version
    store.ObservationStore()                     opens/creates %LOCALAPPDATA%\GhostCursor\kb.sqlite

    if app_info is not None:
        run.hydrate_recipe(recipe, app_info.app_id, store)   <-- BEFORE the tour is built
            for each step: identity.step_key(recipe.intent, step)
                store.observations_for(step_key, app_id)
                    -> replaces step.target_descriptor.confirmed (not merged; store is
                       the single source of truth for learned data — controller ruling P2)

    GuidedTour(recipe, grounder=run.make_grounder(title_re, app_info=app_info, store=store,
               recipe_intent=recipe.intent), ...)

    loop every REFRESH_SECONDS, until ESC/--seconds/DONE/FAILED:
        tour.tick()
            [DECIDING]  grounder(step, i)
                grounding.ground(step, title_re, locale=ui_locale, app_version=app_info.version)
                    rung 1: identity.step_key-scoped select_observations() picks exact
                            version, else nearest LOWER verified, else unknown/global,
                            then cross-checks live control_type before trusting a
                            non-exact match
                    rung 2/3/4: unchanged (control_type+name, UIA-only substring, OCR fuzzy)
                grounding.promote(step, grounded, app_version=app_info.version, locale=ui_locale)
                    writes/updates the in-memory Step's confirmed observation
                run.persist_step(recipe.intent, step, app_id, store)
                    identity.step_key(recipe.intent, step)
                    store.record(step_key, app_id, observation)   upsert, PK (step_key,
                        app_id, app_version, automation_id) -> idempotent, no unbounded growth

  finally:
      window.destroy_overlay_window(hwnd)   <-- store.close() runs in this same finally
      store.close()
```

Verified end to end by running the same recipe as two separate child
processes against a scratch database: run 1 grounded at rung 2 (name match,
`hydrated=0`); run 2 grounded at rung 1 using the id run 1 learned
(`hydrated=1`); deleting the database file returned a third run to
`hydrated=0, rung=2` — promotion is real, disk-backed, and erasable.

---

## Future milestones (not yet started)
1. Ghost Cursor MVP capstone — tier 3 of the perception ladder (the VLM
   pointing model; UIA and OCR are built), streaming local inference,
   entity-scoped memory, Tauri packaging
See the build doc's checklist for the exhaustive list; this file grows a
section per milestone as they're started.
