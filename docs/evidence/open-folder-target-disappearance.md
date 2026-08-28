# Open Folder: the action removes its own target

Measured 2026-08-28 on VS Code **1.135.0.0**, window `Welcome - Visual Studio
Code` (hwnd 263404), through the acceptance harness with the new timing
landmarks (D075). Two runs, same setup, opposite outcomes.

## The two timelines

| Mark | Run 1 — passed | Run 2 — failed |
|---|---|---|
| `first_observation_s` | 0.25 | 0.25 |
| `first_hint_s` | 1.00 | 1.00 |
| `verification_started_s` | 5.531 | 6.281 |
| `title_changed_s` | 5.781 | 6.781 |
| `ended_s` | 6.031 | 16.828 |
| outcome | `passed`, 1/1, UIA-only | `failed`, 0/1, UIA-only |
| detail | — | `cannot find 'Open Folder...' on screen` |

Records: `.artifacts/task8-smoke/open_folder-smoke1.json` and
`open_folder-smoke2.json` (ignored; the table above is the record).

## What the marks establish

Run 2's **goal was achieved**: `title_changed_s = 6.781` is the verified
outcome occurring. The run still reported failure, 10.047s later, with the
grounding-failure message. `DEFAULT_GROUNDING_GRACE_S` is 10.0
(`ghostcursor/reasoning/loop.py:26`), and `16.828 − 6.781 = 10.047`, so
grounding began failing continuously at almost exactly the moment the title
changed.

The mechanism is directly observable. Probing the same window immediately
after the action:

```
window: 263404 'matcher.py - ai-finance-controller - Visual Studio Code'
after the action: {'open_folder': 0}
```

**Opening a folder replaces the Welcome page, so the step's action removes the
step's own target.** From that moment the target is ungroundable, and the
grounding grace — which exists for a minimised window or an alt-tab *before*
the action — starts counting down against a step that has already succeeded.

Whether the step passes is therefore a race between the title-change
verification and the target's disappearance. The two runs differ only in the
gap between action detection and title change: 0.25s and the verification won;
0.5s and grounding failure won.

## What this does NOT establish

That this is the same cause as the original 0/3 failures. Those were reported
with a different symptom (the cursor staying on Open Folder until a 20-second
verification timeout, not a 10-second grounding failure), and no record of
them survives. It is a plausible relative, not a proven identity. The defect
here is real and reproduced on its own terms, which is enough to act on.

## Status

Open. Task 9 must not begin while a certified workflow's success depends on a
sub-second race. See `docs/superpowers/FOLLOWUPS.md` for the proposed fix
direction.
