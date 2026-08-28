# Compiled observation walk latency, live VS Code

Measured 2026-08-28 on VS Code **1.135.0.0**, window
`Mermaid Diagram - enterprice agent ecommerce - Visual Studio Code`
(hwnd 1706624), via `.artifacts/walk-cost-probe.py`, which alternates the two
shapes on the same window so a warming tree cannot be read as a faster call.

| Round | `descendants()` | controls | `descendants(control_type="Button")` | controls |
|---|---|---|---|---|
| 1 | 0.093s | 169 | 0.047s | 49 |
| 2 | 0.110s | 169 | 0.031s | 49 |
| 3 | 0.094s | 169 | 0.046s | 49 |

One complete compiled plan tick, measured separately on the Welcome window
during Open Folder setup: **0.063s**, of which the Button walk was 0.047s and
returned 45 controls, one of which matched `open_folder`.

## What this supports, and what it does not

The type-scoped walk is **2–3× cheaper** than the full tree here, and it is the
walk both VS Code workflows were certified against. Those are the reasons D074
gives for restoring it, alongside CLAUDE.md's standing prohibition on the
generic full Electron descendant walk for these targets.

**It does not support the claim that the full-tree walk caused Open Folder's
earlier 0/3.** A ~0.1s tick cannot produce a 20-second verification timeout.
That causal story was asserted before this measurement existed and is
withdrawn.

Open Folder passed 3/3 on the same day the walk changed, but the two are not
shown to be connected. Other differences between the failing and passing
attempts were not controlled — notably that the passing runs pinned the target
with `--target '^Welcome - Visual Studio Code$'` while the earlier attempts
bound whichever VS Code window was found first, and that the earlier failure
was reported from a session whose conditions were not recorded. **The cause of
the original failure remains unexplained.**

This note exists because the opposite claim was nearly committed on the
strength of a probe that polled `GetWindowText` from a separate process and
never observed the perception worker at all — a figure that could not show what
it was cited for (D034).

## Reproducing

```powershell
py -3.12 -c "import win32gui; win32gui.EnumWindows(lambda h,_: None, None)"  # find the hwnd
$env:PYTHONPATH = 'D:\PROJECTS\AIOS'
py -3.12 .artifacts/walk-cost-probe.py <hwnd> Button 3
```

The probe lives under ignored `.artifacts/`; the numbers above are the record.
