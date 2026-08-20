# Mutation ledger — Task 2: the bar window

Plan: `.superpowers/sdd/2026-08-21-control-bar/task-2-brief.md`
Branch: `control-bar`
Files: `ghostcursor/overlay/bar.py`, `ghostcursor/overlay/window.py`, `tests/test_bar.py`
Baseline (all 4 `test_bar.py` tests + full fast suite passing, no mutation applied): `e507677`

Per D018, each mutation below was applied to `ghostcursor/overlay/bar.py`
one at a time, verified to fail `python -m pytest tests/test_bar.py -v`,
then reverted before the next mutation. Reverts were verified clean against
`e507677` (`git diff --stat` showed no changes to `bar.py`/`window.py`) before
moving to the next mutation.

## A finding before the results: mutation 3 as specified did not fail

The brief's `test_destroying_the_bar_does_not_end_the_message_loop` calls
`bar.destroy_bar_window(bar_hwnd)`, then asserts
`win32gui.PumpWaitingMessages() != 1`. But `destroy_bar_window()` itself ends
with a call to `pump_messages_nonblocking()` — so by the time the test's own
`PumpWaitingMessages()` runs, the WM_QUIT already posted by a broken
`_bar_wnd_proc` has already been dequeued *inside* `destroy_bar_window()`.
The test's own pump call then sees an empty queue and passes regardless of
whether the bug is present.

Confirmed directly: calling `win32gui.DestroyWindow(bar_hwnd)` (bypassing the
helper) followed by `win32gui.PumpWaitingMessages()` returned `1` against a
mutated `_bar_wnd_proc`; going through `bar.destroy_bar_window()` first and
then pumping again returned `0` for the identical mutated code. Applying
mutation 3 below and running the brief's original test unmodified: **4 passed**
(should have been 1 failed).

Fix: changed the test to call `win32gui.DestroyWindow(bar_hwnd)` directly
instead of `bar.destroy_bar_window(bar_hwnd)`, so the test's own
`PumpWaitingMessages()` call is the first thing to touch the queue after
`WM_DESTROY` is dispatched. Re-ran mutation 3 against the fixed test: it now
fails as intended (see below). This fix is committed in `tests/test_bar.py`.

## Results

| # | Mutation | Must fail | Actually failed | Result |
|---|---|---|---|---|
| 1 | Add `WS_EX_NOACTIVATE` to the bar's `ex_style` | `test_the_bar_can_be_clicked_and_focused_and_the_overlay_cannot` | same test only (3 passed, 1 failed) | PASS |
| 2 | Add `WS_EX_TRANSPARENT` to the bar's `ex_style` | same test | same test only (3 passed, 1 failed) | PASS |
| 3 | Make `_bar_wnd_proc` call `win32gui.PostQuitMessage(0)` on `WM_DESTROY` | `test_destroying_the_bar_does_not_end_the_message_loop` | same test only, **after** fixing the test's own blind spot (see finding above) — the brief's original test passed all 4 unmodified | PASS (after test fix) |
| 4 | Make the bar full-screen (`x, y, _BAR_WIDTH, _BAR_HEIGHT` replaced with `left, top, width, height` from `virtual_screen_rect()`) | `test_the_bar_is_not_full_screen` | same test only (3 passed, 1 failed) | PASS |

### Mutation 1 failure output (verbatim)

```
AssertionError: bar cannot take focus
assert not (134217864 & 134217728)
 +  where 134217728 = win32con.WS_EX_NOACTIVATE
```

### Mutation 2 failure output (verbatim)

```
AssertionError: bar cannot receive clicks
assert not (168 & 32)
 +  where 32 = win32con.WS_EX_TRANSPARENT
```

### Mutation 3 failure output, against the fixed test (verbatim)

```
AssertionError: destroying the bar posted WM_QUIT -- the tour's own loop would end
assert 1 != 1
 +  where 1 = <built-in function PumpWaitingMessages>()
 +    where <built-in function PumpWaitingMessages> = win32gui.PumpWaitingMessages
```

### Mutation 4 failure output (verbatim)

```
AssertionError: bar is more than half the desktop wide
assert (1920 - 0) < (1920 // 2)
```

All four mutations were reverted after being observed to fail their test, and
the full `test_bar.py` suite (4 passed) plus the full fast suite (341 passed)
were confirmed green again before this ledger was written.
