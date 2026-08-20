# Wrong-Action Feedback — Design

Date: 2026-08-20
Status: approved, pending implementation plan
Scoped in: `docs/superpowers/FOLLOWUPS.md` §"Wrong-action feedback"

**Measurements: this document is the PRIMARY RECORD for every focus number
below.** They come from two throwaway probes run on 2026-08-20 against this
machine and are recorded nowhere else — the probe scripts were scratch and are
not in the repo. Cited under D034 on that basis: they are written down here
first, and quoted from here afterwards. Nothing below is estimated.

---

## 1. Why

The system verifies that the **world** reached the expected state. It never
verifies that the **user** did the expected thing. Those come apart in a way
that matters for a product whose entire job is teaching:

- The user clicks the wrong control and then the right one. Verification
  passes. The tour advances in silence, and the user is never told they took a
  detour — so they learn nothing from it.
- The user clicks the wrong control and stops. The loop dwells, says nothing,
  and eventually re-hints once on the idle timer. The user is left to work out
  on their own that nothing happened.

The loop already *detects* something here. `AWAITING_USER_ACTION` has an
`elements_changed` branch whose comment reads "the world changed, but not into
what we predicted — the user did something else", and it re-observes. What it
does not do is **say so**. This design closes that.

**Why `elements_changed` is not the signal.** It fires on any element-identity
change, and this project has already measured VS Code's element identity
churning in steady state with no user action at all
(`2026-08-19-cold-electron-probe-findings.md` §3). Announcing "you did the wrong
thing" on application churn is precisely the Clippy failure mode the loop is
built to avoid. A signal that fires when the user did nothing is worse than no
signal.

## 2. The signal, and what was measured

**Focus.** A focus change is caused by a user interacting with a control; it
does not drift on its own the way the element set does.

`Snapshot.focused_automation_id` already exists for this and is hardcoded `""`.
`FOCUS_MOVES_TO` verification raises `NotImplementedError` and its docstring
names that hardcoding as the reason. Focus tracking was designed for and never
built.

### 2.1 Reading focus is cheap

`IUIAutomation::GetFocusedElement`, 40 samples:

| | |
|---|---|
| median | **2.66 ms** |
| min / max | 1.84 ms / 20.54 ms |
| over 100 ms | 0 |
| over 500 ms (D020's tick ceiling) | 0 |

Nowhere near the budget that makes a perception step dangerous.

### 2.2 Focus carries the identity grounding keys on

Probe 1 returned an empty AutomationId for all 40 samples, which looked fatal —
grounding keys on AutomationId at rung 1. It was an artifact: focus was on a
console window, which genuinely has none. Re-probed against real controls
(`tests.uia_app.SyntheticApp`), focusing each in turn:

| Control focused | `GetFocusedElement` reports | Tree walk reports | Match |
|---|---|---|---|
| Export button | `aid='1001'` | `aid='1001'` | yes |
| Delete button | `aid='1002'` | `aid='1002'` | yes |
| Filename edit | `aid='1004'` | `aid='1004'` | yes |

1.02–1.30 ms per read. **The id focus reports is the same id grounding walks
against**, which is what makes the comparison meaningful rather than
approximate.

Recorded because it nearly killed the design: a single unrepresentative probe
said "focus has no identity", and the correct conclusion was "the probe was
pointed at the wrong thing".

### 2.3 Sampling rate is the real constraint

Worker cadence is `REFRESH_SECONDS = 0.25` plus a walk of 0.18–0.70 s, so focus
sampled once per walk lands every **0.4–1.0 s**. A user clicking the wrong
control and correcting themselves does it in well under a second. Sampling at
walk cadence would therefore miss the first of the two motivating cases —
the one FOLLOWUPS names first.

## 3. Design

### 3.1 Perception: the worker samples, and only perceives

The worker keeps walking at its current cadence. Its inter-walk wait changes
from one `stop.wait(interval_s)` into ~50 ms slices, each reading focus. Between
publishes it accumulates the distinct AutomationIds focus **visited**, not the
one it happens to rest on when the next walk completes. Visiting is what catches
wrong-then-right; resting does not.

The worker filters on exactly two things, both perception facts:

- focus is inside the target window's process (`GetWindowThreadProcessId` on the
  handle `first_matching_hwnd` already provides)
- the focused element has a non-empty AutomationId

It does **not** decide whether the control was the wrong one. Only the tick loop
knows which step is current and what it is grounded to. This is the split D028
already established for tier 2 — *the UI thread decides, the worker executes and
publishes* — and it is kept deliberately clean rather than letting the worker
acquire step context.

### 3.2 What crosses the thread boundary

Primitives only (D021). No COM object, no retained focus element.

| Field | Meaning |
|---|---|
| `Snapshot.focused_automation_id: str` | Focus at walk time. Fills the field that already exists. |
| `Observation.focus_visited: tuple[str, ...]` | Distinct in-app AutomationIds focus touched since the last publish. Capped at 8 so a control cycling focus cannot grow it without bound. |

### 3.3 Reasoning: the decision

In `AWAITING_USER_ACTION`, ordered deliberately:

1. **Satisfied wins.** If verification passes, the step advances and nothing
   scolds the user — including when `focus_visited` shows a detour. The console
   records the detour; the tour does not interrupt a success to criticise it.
   Interrupting success is the Clippy failure. **At most one such line per
   step**, and it does NOT count toward §3.5's cap, which counts re-hints —
   on this path no ring is re-asserted, because the step is over.
2. **Not satisfied, and `focus_visited` holds an id that is not the grounded
   target's** → print one console line naming what was touched, then
   `State.OBSERVING`.
3. Otherwise the existing `elements_changed` and idle-timeout branches are
   unchanged.

### 3.4 The re-hint is the existing path, not a new one

**No `renderer.show()` call is added to this branch.** `OBSERVING` already
re-grounds and flows through `RENDERING_HINT`, which re-shows the ring.

This is not merely convenient. D027 exists because a second corrective overlay
write is not a narrow race: `set_hint` ends in `UpdateWindow`, which paints
synchronously, so an extra frame definitely reaches the screen. Re-hinting
through the existing path keeps the single write path intact.

"Immediate" therefore means *without waiting out the idle timer* — a few ticks
rather than the full timeout. Re-grounding first is also correct on its own
terms: a wrong click may have opened a dialog and moved the target.

### 3.5 Nagging bound

A separate counter, capped at **3** wrong-action re-hints per step, after which
the ring stops re-asserting and only the console records. The cap counts
**re-hints, not messages**: past the cap the loop still transitions to
OBSERVING and still prints, it simply stops re-asserting the ring. Silence
about a wrong action would be worse than a quiet one — and capping the message
too would mean a user who keeps genuinely trying and failing gets told LESS the
harder they are struggling, which is backwards for a system whose whole purpose
is teaching. The print is bounded by real user actions, not by wall clock, so it
cannot produce the unbounded nagging the re-hint cap exists to prevent. The idle-timeout cap
of 1 is unchanged.

Different caps because they are different situations. Idle means the user is
doing nothing, and a second nudge is nagging. A wrong action means the user is
actively trying, and answering each attempt is help — but not without a bound.

## 4. When it stays silent, deliberately

| Situation | Behaviour | Why |
|---|---|---|
| Focused control has no AutomationId | Silent | Cannot name what was touched. Never accuse without naming. |
| Focus outside the target process | Silent | Alt-tabbing to Slack is not a mis-click. |
| Focus read raises | Silent; the walk is unaffected | Same shape as `_safe_hwnd`: the walk is the product, focus is a nicety. |
| **Target grounded via OCR** | **Silent** | OCR elements carry no AutomationId, so there is nothing to compare. This falls out of the firing policy rather than needing a special case — but it means wrong-action feedback **does not exist on OCR-grounded steps**, and that is stated here as a plain property rather than left to be discovered. |
| No grounded target yet | Silent | Nothing to be wrong about. |

## 5. Testing

- Sequence tests on an injected clock (D026), with focus supplied through an
  injectable source the way `hwnd_source` is — no test needs real focus.
- The worker-side accumulation gets its **own** test with a fake focus source.
  The loop-side decision test is not sufficient: the invariant only implies the
  property if `focus_visited` genuinely reflects what focus touched.
- Every silence case in §4 gets a test that fires nothing.
- Mutation-verify (D018): deleting the wrong-action branch must fail the fire
  test; making it fire unconditionally must fail each silence test; removing the
  in-process filter must fail the out-of-app silence test.

Stated per D031 — property: *a user who acts on the wrong control is told, and
the hint re-asserts*. Invariant: *a non-target in-app AutomationId in
`focus_visited`, with verification unsatisfied, produces exactly one console line
and a transition to OBSERVING*. The invariant implies the property **only if**
`focus_visited` is faithful, which is why §5's second bullet is not optional.

## 6. `FOCUS_MOVES_TO`, in its own task

This milestone removes the blocker that `FOCUS_MOVES_TO`'s `NotImplementedError`
names. Leaving a deliberate "not implemented because X" raise in place after X
is fixed makes the codebase lie about itself, and costs the next reader an
investigation to discover the note is stale.

Enabled here, but as a **separate task with its own tests**, because a
verification kind that advances a tour deserves its own coverage rather than
riding in on a feature that merely happens to unblock it.

## 7. Deferred, with a named trigger

**Native UIA focus-change events** (`AddFocusChangedEventListener`) would remove
the sampling gap entirely. Not built.

**Corrected figure (an earlier version of this section understated the gap by
roughly an order of magnitude; see D034 — a documented number the
implementation did not support, cited as the basis for this exact deferral).**
Focus is sampled ONLY during the inter-walk wait, in `focus_slice_s` slices
(50 ms by default) plus one extra sample recovered at the start of each walk
(section 3.2). It is NOT sampled during the walk itself (0.18–0.70 s,
measured, section 2.3) or during tier 2 when a request is standing (capture
plus OCR, 0.14–0.23 s measured, D028–D030). The real contiguous blind window
is therefore **walk plus tier 2, 0.18–0.93 s**, not the 50 ms this section
previously claimed — that 50 ms was the slice interval, not the gap the
slicing leaves open. Against a cadence of `interval_s` (0.2 s) sampled plus
that 0.18–0.93 s unsampled, coverage is roughly **18–53% of wall time**, not
"faster than a human performs two deliberate clicks". A wrong-then-right
round trip completing inside the blind window is well within normal human
click speed, not faster than it.

The cost of closing the gap with native events is unchanged and still real:
COM event callbacks arrive on RPC-managed threads and would need marshalling
into the worker's apartment — precisely the area D021 warns gives "confusing
intermittent failures rather than a clean error", and an area this project has
already paid the cost of avoiding once. Polling is kept anyway, but the
justification for keeping it has to be honest about what it costs: it is
"avoid a real COM-marshalling risk", not "the gap is negligible".

**Trigger for revisiting:** any report of a wrong action going unremarked —
not "evidence that real use is missing wrong actions" as this section
previously said, which reads as a much higher bar than a gap this size
warrants, and not the theoretical existence of the gap, which is already
known, measured, and accepted here.

## 8. Out of scope

Any new perception tier. Any VLM. Borrowing the perception half of a
computer-use agent (screenshot, ask a model "did that work") is explicitly
rejected in FOLLOWUPS: it replaces a structured UIA state-diff with a pixel
guess, and D003 says reach for tier 3 last. Nothing here moves the cursor or
synthesises input (D006).

## 9. What these measurements do not establish

- Focus identity was confirmed on `SyntheticApp`'s plain Win32 BUTTON/EDIT
  controls. **Chromium and Acrobat were not probed for focus.** Their controls
  frequently lack AutomationIds, so §4's OCR/no-id silence case is expected to
  be common there — how common is unmeasured.
- The 50 ms slice interval is chosen against human click speed, not measured
  against real users fumbling.
- Cost was measured on one machine, idle. `GetFocusedElement` against a
  non-pumping window was **not** tested; the hung-window tax measured at
  6.28 s vs 100.13 s (D025) applies to UIA calls generally, and whether focus
  reads pay it is unknown.

  **What that would cost if it does.** The read happens on the perception
  worker, never the UI thread, so a block stalls perception exactly the way a
  slow walk already does — the UI thread keeps pumping messages and polling
  ESC (D021), and the staleness ladder ages the hint as designed. The failure
  mode is degraded perception, not a frozen overlay the user cannot dismiss.
  That is the whole reason the read is specified on the worker rather than
  inline in the tick loop, where 1-3 ms would otherwise look tempting.
