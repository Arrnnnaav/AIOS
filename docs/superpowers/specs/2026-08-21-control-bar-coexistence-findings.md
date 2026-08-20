# Control Bar Coexistence — Gating Spike Findings

Date: 2026-08-21
Gate for: `docs/superpowers/plans/2026-08-21-control-bar.md`, Task 1
Design: `docs/superpowers/specs/2026-08-21-control-bar-design.md` §8

**This document is the PRIMARY RECORD for these results.** The probe was a
throwaway script in a scratch directory and is not in the repo, so under D034
the observations are written down here first and cited from here afterwards.
Nothing below is estimated.

---

## Verdict: **GATE PASSES**

All six checks passed on one run against real windows. Tasks 2-6 may proceed.

## Why this was gated rather than assumed

Every task in the control-bar plan assumes a second, focusable, topmost window
can coexist with a full-screen topmost click-through overlay. That was reasoned
from documented Win32 behaviour and had never been tested in this repo. This
project has been surprised three times by exactly that shape:

- `GetSystemMetrics` silently changing its answer mid-run once anything took a
  screenshot (D010/D013)
- Discord's `Discord Updater` splash being a separate HWND that fully satisfied
  `windows_matching`, which would have absorbed the entire warm-up budget
- `UpdateWindow` painting synchronously, making what looked like a narrow
  two-write race a second frame that definitely reached the screen (D027)

In each case the documentation was right and the behaviour in context was not
what anyone assumed.

## What was observed

| # | Check | Result |
|---|---|---|
| 1 | Both windows visible simultaneously | `overlay=True bar=True` |
| 2 | Styles are the intended inverse | overlay `TRANSPARENT=True NOACTIVATE=True`; bar `TRANSPARENT=False NOACTIVATE=False` |
| 3 | Bar can take foreground; overlay does not | `SetForegroundWindow` raised nothing; `GetForegroundWindow()` returned the bar's handle. **CONDITIONAL — see the correction below.** |
| 4 | A click over the bar lands on the bar | `WindowFromPoint(960, 1028)` → root = the bar's HWND, not the overlay's |
| 5 | Overlay still paints its hint with the bar up | **440 pixels changed** in an 80×80 capture at desktop centre after `set_hint` |
| 6 | Destroying the bar does not end the message loop | `PumpWaitingMessages()` returned `0` (no `WM_QUIT` dequeued); overlay still alive |

Check 4 is the one that mattered most. The overlay is `WS_EX_TRANSPARENT` and
spans the whole virtual desktop, so if it had owned that pixel the bar could
never have been clicked and the design would have been dead.

Check 6 confirms the plan's decision that the bar needs its own window
procedure. The overlay's calls `PostQuitMessage(0)` on `WM_DESTROY`, which is
correct for a window torn down once at exit; a bar closed mid-tour would have
posted `WM_QUIT` and ended the thread's loop. The probe's procedure returns `0`
instead, and the loop survived.

## Correction (2026-08-21, same day): check 3 is conditional, not general

Check 3 as first recorded said the bar "can take foreground". A later run under
pytest measured the same call being **REFUSED**:

```
foreground before SetForegroundWindow: 65902 is_ours: False
SetForegroundWindow: REFUSED -> error: (0, 'SetForegroundWindow', ...)
```

Both observations are correct and neither is a fluke. Windows permits
`SetForegroundWindow` when the calling process is already the foreground process
**or received the last input event**, and refuses it otherwise. The original
probe happened to run in a permitted state; the pytest run did not. The finding
as first written over-claimed by omitting the condition, which is the D034 shape
— a measurement recorded without the circumstances that make it reproducible.

**What this does and does not change:**

- The gate still PASSES. Checks 1, 2, 4, 5 and 6 are unaffected, and check 4 —
  that a click over the bar lands on the bar and not the click-through overlay —
  was always the make-or-break one.
- In real use the bar is focused by a user CLICKING it, which gives our process
  the last input event and satisfies the rule. The design does not depend on
  focusing the bar programmatically.
- Foreground RESTORATION (design §4.4) only attempts while
  `GetForegroundWindow() == bar_hwnd`, i.e. only when we are already foreground
  — precisely the permitted case. The guard was written for a different reason
  (never fight the user for focus) and turns out to also be what keeps the call
  legal.
- **Tests must not assert that foreground actually changed.** They cannot rely
  on being in a permitted state. Assert that the call was ATTEMPTED with the
  right handle instead.

## What this does NOT establish

- **One run, one machine, one monitor configuration.** The bar was placed at
  bottom-centre of the virtual desktop; multi-monitor placement is untested.
- **`SetForegroundWindow` to another process's window is still untested.** Check
  3 gave focus to a window **this process owns**. Foreground restoration
  (design §4.4) is a different case: handing focus to the *target application's*
  window while we are foreground. Windows' foreground lock permits it in
  principle, and design §8 already records that half as unverified — this probe
  does **not** close that gap, and the wording here is deliberate so it is not
  later cited as though it did.
- No click was synthesised. Check 4 used `WindowFromPoint`, which answers "who
  owns this pixel" — the same question a click asks, without generating input
  (D006 forbids synthesising input, and that holds in probes too).
- Nothing here measures whether a visible Stop button is actually *used* in
  preference to ESC. The safety argument is that an invisible escape cannot be
  relied upon, not that this one demonstrably is.
