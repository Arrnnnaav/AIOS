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
| `tests/backdrop.py` | controlled solid-colour window used as a test surface |
| `tests/test_overlay.py` | 14 checks: styles, click-through, transparency, hint placement, stale pixels, teardown |
| `tests/test_end_to_end.py` | 8 checks: perception -> coordinate -> ring lands on the window, off-screen rejection |
| `tests/uia_app.py` | real Win32 window with known AutomationIds, used as deterministic grounding target |
| `ghostcursor/inference/` | empty; later milestones |

### Verification status
```
python -m tests.test_overlay        14/14 pass
python -m tests.test_end_to_end      8/8  pass
python -m pytest tests/             134 passed
```
The first two (pixel harnesses) have their own runner and are not collected by
pytest. Also confirmed against a real Notepad window: 440 ring pixels, 49x49
diameter, centroid within 1px of the requested coordinate. And confirmed
against a real persistence run: a UI AutomationId learned by one process was
reused by a completely separate later process (rung 2 -> rung 1 across
process boundaries), and deleting the database file returned behaviour to
rung 2 — see the persistence call graph above.

### You are here
Intermediate milestone (Single-App Guided Tour) is **COMPLETE** — verified
end-to-end on a real, non-synthetic application, not only the test harness.

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
      window.create_overlay_window()
      GuidedTour(recipe, grounder=run.make_grounder(title_re), snapshotter=verification.take_snapshot,
                 verifier=verification.verify, renderer=OverlayRenderer(hwnd))

      loop every REFRESH_SECONDS (0.25s), until ESC, --seconds, DONE, or FAILED:
          run.escape_pressed()                 GetAsyncKeyState(VK_ESCAPE)
          GetAsyncKeyState(VK_SPACE)            polled -> tour.confirm() for user_confirms steps
          tour.tick()                           the state machine, one transition per tick
              [DECIDING]    grounder(step, i) = run.make_grounder(title_re)()
                                grounding.ground(step, title_re, locale=ui_locale)
                                  perception.uia.iter_elements()   rung 1: automation_id
                                                                    rung 2: control_type+name
                                                                    rung 3: fuzzy name
                                -> GroundedTarget | None
                                grounding.promote(step, grounded, app_version="unknown", locale=ui_locale)
                                  (writes automation_id back to in-memory Step; persists to disk later)
                                -> GroundedTarget | None  (None => FAILED, never a guessed coordinate)
              [RENDERING_HINT]  OverlayRenderer.show(grounded, instruction_text)
                                    window.set_hint(hwnd, centre-of-bbox)
                                    .last_instruction = instruction_text   <-- run.py dedupes prints on this
              [AWAITING_USER_ACTION]  verification.take_snapshot(title_re)   (each tick, this is "after")
                                       verification.verify(rule, before, after)
                                           world-state check, not method (D014)
              [VERIFYING]   step_index += 1; renderer.clear(); back to OBSERVING
          run.py prints "step N: <instruction>" only when it changed since the last tick
          window.pump_messages_nonblocking()

  finally:
      window.destroy_overlay_window(hwnd)   always runs, even on exception
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
