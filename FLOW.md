# FLOW.md

How execution actually travels between files, functions, and modules — what calls
what, in what order. Updated as the codebase grows. The "you are here" marker at
the bottom shows exactly what's being built/modified right now.

---

## Current milestone: Beginner Project — Static Hint Overlay  ✅ working

Goal (from `D:\tracker\docs\ghostcursor\build-the-ghost-cursor-mvp-...docx`,
"Beginner Project" tier): a Win32 layered window that draws a ring around one
UI element found via `pywinauto`, drawn with GDI, refreshed on a timer. No AI,
no reasoning loop yet.

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
| `ghostcursor/run.py` | entry point, timer loop, ESC/timeout safety, arg parsing |
| `ghostcursor/overlay/dpi.py` | declares DPI awareness at import; one coordinate space |
| `ghostcursor/overlay/window.py` | layered click-through window, WM_PAINT rendering |
| `ghostcursor/perception/uia.py` | UIA element/window lookup + raw win32 fallback |
| `tests/backdrop.py` | controlled solid-colour window used as a test surface |
| `tests/test_overlay.py` | 14 checks: styles, click-through, transparency, hint placement, stale pixels, teardown |
| `tests/test_end_to_end.py` | 4 checks: perception -> coordinate -> ring lands on the window |
| `ghostcursor/reasoning/`, `memory/`, `inference/` | empty; later milestones |

### Verification status
```
python -m tests.test_overlay        14/14 pass
python -m tests.test_end_to_end      4/4  pass
```
Also confirmed against a real Notepad window: 440 ring pixels, 49x49 diameter,
centroid within 1px of the requested coordinate.

### You are here
Intermediate milestone (Single-App Guided Tour) is **in progress**. The
`IDLE → OBSERVING → DECIDING → RENDERING_HINT → AWAITING_USER_ACTION →
VERIFYING` state machine, the grounding ladder, live UIA verification, the
Win32 renderer adapter, and the `run.py --recipe` entry point are all built
and wired together end-to-end against the synthetic test app. The knowledge
base (spec sections 8-10 — persisting confirmed observations across runs,
locale/version-scoped lookup) is **not built yet**; `promote()` writes
learned `automation_id`s back onto the in-memory `Step`, but nothing
persists them to disk between processes.

### Runtime call graph — guided tour (as built)

```
run.main()
  run.run_tour(recipe_path, title_re, seconds)
      schema.Recipe.load(recipe_path)
      window.create_overlay_window()
      GuidedTour(recipe, grounder=grounding.ground, snapshotter=verification.take_snapshot,
                 verifier=verification.verify, renderer=OverlayRenderer(hwnd))

      loop every REFRESH_SECONDS (0.25s), until ESC, --seconds, DONE, or FAILED:
          run.escape_pressed()                 GetAsyncKeyState(VK_ESCAPE)
          GetAsyncKeyState(VK_SPACE)            polled -> tour.confirm() for user_confirms steps
          tour.tick()                           the state machine, one transition per tick
              [DECIDING]    grounding.ground(step, title_re)
                                perception.uia.iter_elements()   rung 1: automation_id
                                                                  rung 2: control_type+name
                                                                  rung 3: fuzzy name
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

Next: persist confirmed observations (the knowledge base) so a promoted
`automation_id` survives across process runs and can be selected by
`(user_id, app_id, app_version, locale)` instead of being re-learned every
launch — the last piece of the Intermediate milestone's scope per the build
doc.

---

## Future milestones (not yet started)
1. Ghost Cursor MVP capstone — full tiered perception (UIA → OCR → VLM),
   streaming local inference, entity-scoped memory, Tauri packaging
See the build doc's checklist for the exhaustive list; this file grows a
section per milestone as they're started.
