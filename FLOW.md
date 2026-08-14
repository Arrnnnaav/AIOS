# FLOW.md

How execution actually travels between files, functions, and modules — what calls
what, in what order. Updated as the codebase grows. The "you are here" marker at
the bottom shows exactly what's being built/modified right now.

---

## Current milestone: Intermediate Project — Single-App Guided Tour  ✅ complete

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
| `ghostcursor/reasoning/grounding.py` | turn step descriptions into live screen rectangles via 3-rung matching ladder |
| `ghostcursor/reasoning/verification.py` | check world state to decide if user completed a step |
| `ghostcursor/reasoning/loop.py` | observe-act-verify state machine (IDLE → OBSERVING → DECIDING → RENDERING_HINT → AWAITING_USER_ACTION → VERIFYING) |
| `ghostcursor/reasoning/renderer.py` | adapt loop's Renderer protocol onto the Win32 overlay |
| `ghostcursor/reasoning/recipes/synthetic_export.json` | hand-authored recipe for the synthetic test app |
| `ghostcursor/perception/appinfo.py` | identifies the app owning a window (HWND -> PID -> exe path -> file/Appx version) for version-scoped observation lookup |
| `ghostcursor/reasoning/identity.py` | `step_key()` — durable hash of intent + claimed descriptor, the key observations are stored/retrieved under |
| `ghostcursor/memory/store.py` | `ObservationStore` — local SQLite knowledge base of learned observations, keyed by `(step_key, app_id, app_version, automation_id)` |
| `ghostcursor/perception/service.py` | `PerceptionService` — runs the UI-tree walk on a worker thread that owns its COM apartment, and publishes one timestamped `Observation` into a single overwritten slot |
| `ghostcursor/perception/health.py` | `WorkerHealth.check()` — notices a dead or stalled worker, restarts it exactly once, then ends the tour with a reason |
| `ghostcursor/reasoning/staleness.py` | `StalenessLadder` — how old the last confirmed-fresh walk is, as `Freshness.FRESH / DIMMED / HIDDEN`, with debounced recovery |
| `tests/backdrop.py` | controlled solid-colour window used as a test surface |
| `tests/hung_window.py` | child process that creates a window and then stops pumping messages — reproduces the 41s UIA block deterministically |
| `tests/test_hung_window.py` | `HungWindow` context manager + the block measurement; the fixture Tasks 5-7 are built on |
| `tests/test_run_threaded.py` | ESC stays responsive while the target is hung — the property this whole design exists for |
| `tests/test_overlay.py` | 15 checks: styles, click-through, transparency, hint placement, dimmed-ring colour, stale pixels, teardown |
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
python -m tests.test_overlay         15/15 pass
python -m tests.test_end_to_end       8/8  pass
python -m pytest tests/ (fast)      165 passed   excludes the three slow files below
python -m pytest tests/test_run_threaded.py \
                tests/test_perception_service_hung.py \
                tests/test_hung_window.py            11 passed in 88s
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
Perception now runs **off the UI thread** (D021-D024). The escapability
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
`IDLE -> OBSERVING -> DECIDING -> RENDERING_HINT -> AWAITING_USER_ACTION ->
VERIFYING` state machine, the grounding ladder, live UIA verification, the
Win32 renderer adapter, the `run.py --recipe` entry point, and now
persistence — promotion survives process exit via `ObservationStore`, keyed
by `(step_key, app_id, app_version, automation_id)`, hydrated before each
tour and written on every promotion — are all built and wired together
end-to-end. What remains unbuilt is the doc-ingestion knowledge base: web
search, doc ingestion, embeddings, intent matching, recipe distillation,
OCR, and VLM (spec sections outside 9-10).

### Runtime call graph — guided tour (as built)

```
run.main()
  run.run_tour(recipe_path, title_re, seconds)
      schema.Recipe.load(recipe_path)

      --- perception moves OFF this thread, before the overlay exists ---
      service.PerceptionService(title_re).start()
          worker thread: CoInitializeEx, then forever:
              uia.iter_elements(title_re)                  ~40s against a hung target
              verification.take_snapshot(..., observed_at)  timestamped from the service clock
              -> publishes ONE Observation into a slot (overwrite; no queue, no history)
      staleness.StalenessLadder()      how old the last CONFIRMED-FRESH walk is
      health.WorkerHealth(service, ladder)   restart once, then end the tour

      window.create_overlay_window()
      GuidedTour(recipe, grounder=run.grounder_from_slot, snapshotter=run.snapshotter,
                 verifier=verification.verify, renderer=OverlayRenderer(hwnd))

          run.snapshotter()          service.latest() -> Observation | None
                                     None -> empty Snapshot (observed_at 0.0, reads as FRESH)
                                     ladder.observed() ONLY when observed_at ADVANCES —
                                     re-reading the same slot must not reset the clock
          run.grounder_from_slot()   service.latest() -> make_grounder(...)(step, i, obs.elements)
                                     grounds the LAST observation, so a merely-stale slot keeps
                                     succeeding and the loop's grounding grace never starts

      loop every REFRESH_SECONDS (0.25s), until ESC, --seconds, DONE, FAILED, or health:
          run.escape_pressed()                 GetAsyncKeyState(VK_ESCAPE) — never blocked now
          GetAsyncKeyState(VK_SPACE)            polled -> tour.confirm() for user_confirms steps
          health.check()                        once per tick; suppressed until the first
                                                observation lands or dead_after_s from tour start
                                                (ladder.age() is inf before then)
          tour.tick()                           the state machine, one transition per tick
              [DECIDING]    grounder(step, i, elements)
                                grounding.ground(step, title_re, elements=obs.elements)
                                                                    rung 1: automation_id
                                                                    rung 2: control_type+name
                                                                    rung 3: fuzzy name
                                grounding.promote(step, grounded, app_version, locale=ui_locale)
                                  (writes automation_id back to in-memory Step; persists to disk)
                                -> GroundedTarget | None  (None => clear hint, grounding grace
                                   (dead_after_s + 10s, so a perception failure is always named
                                   as one and never as a missing element), then FAILED;
                                                           never a guessed coordinate)
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
                    rung 2/3: unchanged (control_type+name, fuzzy name)
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
1. Ghost Cursor MVP capstone — full tiered perception (UIA → OCR → VLM),
   streaming local inference, entity-scoped memory, Tauri packaging
See the build doc's checklist for the exhaustive list; this file grows a
section per milestone as they're started.
