# Control Bar and Intent Input — Design

Date: 2026-08-21
Status: approved, pending implementation plan
Scoped in: `docs/superpowers/FOLLOWUPS.md` §"Control bar and intent input"

---

## 1. Why

Two gaps, one of them a safety gap.

**There is no way to say what you want.** The only entry point is
`--target` / `--recipe` / `--seconds`. A user cannot state a goal.

**The only escape is invisible.** ESC is the sole way out of a full-screen,
topmost, click-through overlay, and nothing on screen says so. `run.py` prints
it once at startup and the overlay itself has no chrome — it cannot, because it
must never take focus or receive clicks (D006, D009). An escape hatch a user
cannot see is one they cannot use when they need it most.

A visible Stop button closes the second gap directly. That is the primary
justification for this milestone; intent capture rides along because it needs
the same window.

## 2. Scope

**In:** a second, focusable window with Stop, Pause, a click-to-open text box
that captures a goal, and a status line.

**Explicitly out, decided rather than deferred by omission:**

- **Voice input.** Removed from scope. A mic is not a button but a subsystem:
  cloud speech-to-text would breach D017's no-network rule outright, and local
  speech-to-text means a Whisper-class model plus an audio stack — a dependency
  footprint comparable to the whole tier-2 OCR milestone. Revisit as its own
  milestone. §4.3 records how the focus rule accommodates it without rework.
- **Turning the typed goal into steps.** `ghostcursor/inference/` is empty and
  only `--recipe` drives a tour. Planning is the inference milestone. This one
  captures and displays the goal; it does not act on it. The honest framing is
  that the bar makes the system **controllable, not yet instructable**.

## 3. The window

### 3.1 A second Win32 window on the same UI thread

`GhostCursorBar`: its own window class, created on the UI thread that already
owns the overlay. Small and edge-positioned — never full-screen, never over the
region a hint is likely to occupy.

Its styles are the deliberate inverse of the overlay's
(`ghostcursor/overlay/window.py`, the `ex_style` block):

| | Overlay | Bar |
|---|---|---|
| `WS_EX_TOPMOST` | yes | yes |
| `WS_EX_TOOLWINDOW` | yes | yes |
| `WS_EX_LAYERED` | yes (colorkey) | no |
| `WS_EX_TRANSPARENT` | **yes** — never intercepts clicks | **no** — must receive them |
| `WS_EX_NOACTIVATE` | **yes** — never takes focus | **no** — must be able to |

Both are topmost, so z-order between them is activation order and the bar rises
when clicked. The overlay being click-through means it never intercepts a click
meant for the bar regardless of order.

### 3.2 Why the same thread, and why not the alternatives

**It costs no new message loop.** `window.pump_messages_nonblocking()` calls
`PumpWaitingMessages()`, which pumps every window on the calling thread. The
bar is pumped by the call `run.py` already makes each tick.

The usual objection — a slow tick freezes the bar — does not apply here.
**D021 already moved perception onto a worker thread precisely so the UI thread
never blocks**; a hung target costs 41 seconds on the worker, not on this
thread. The bar inherits a responsiveness guarantee that already exists and is
already covered by the hung-target suite.

**Not a second thread.** It would insulate the bar from a tick loop that D021
already guarantees will not block it, and would pay for that with cross-thread
window and state handling — the area D021 warns gives "confusing intermittent
failures rather than a clean error". A known risk bought for an unneeded
benefit.

**Not tkinter.** It brings its own event loop, making three interleaved loops in
one process, and its DPI handling conflicts with D010's manual per-monitor
awareness — the rule that exists because `GetSystemMetrics` silently changed its
answer mid-run the first time anything took a screenshot.

### 3.3 Class registration

`create_overlay_window()` guards its class registration with a module-global
`_class_registered`. A second class must not mean a second global: registration
moves into a small shared helper keyed by class name. Two globals tracking two
classes is how a third one gets forgotten.

## 4. Focus and input arbitration

### 4.1 The state is the arbitration

SPACE confirms a step and ESC quits, both polled globally with
`GetAsyncKeyState` (`run.py`'s `escape_pressed` / `should_poll_space`) because
the overlay never has focus. A focusable text box collides with both: typing a
space would confirm a step, and ESC would quit mid-sentence.

Two states resolve it without a second mechanism:

**Collapsed** — `[ Ask ] [ Stop ] [ Pause ]` and a status line. No focusable
widget exists. The bar receives clicks without ever calling `SetFocus`, so the
target app keeps focus and ESC and SPACE poll exactly as today.

**Expanded** — clicking Ask creates the `EDIT` control as a CHILD of the bar
and focuses it. Because it is a child, `GetForegroundWindow()` returns the bar's
own handle, which is what §4.2's test compares against. While it holds focus,
SPACE polling is suppressed and ESC is REBOUND (below); keys belong to the box.
Submitting or dismissing destroys the control and normal polling resumes.

**Getting out of the box.** Three ways, deliberately, because the key a user
would reach for first is the one that must not quit the tour:

| Action | Result |
|---|---|
| Enter | Submits the goal, closes the panel. Enter is not globally polled, so it collides with nothing. |
| A visible close control on the panel | Closes without submitting. The back-arrow principle: a mouse route out that never depends on focus or keys. |
| **ESC** | **Closes the panel. It does NOT quit the tour.** |

ESC is rebound rather than deadened. In every other application ESC in a text
box means "dismiss this", and honouring that costs nothing here: the panel
closes, focus and polling return to normal, and a SECOND ESC then quits the tour
as it always has. A user hammering ESC to get out of everything gets the locally
sensible thing each time, and still reaches the global escape on the next press.
An ESC that silently did nothing would be worse than either behaviour.

Suppression is user-initiated, visible, and exited by a click. The open box is
itself the cue that typing mode is on — which is why suppressing ESC is
acceptable here and would not be if the field were always present.

### 4.2 `GetForegroundWindow` is the ground truth, not a flag

The suppression test is `GetForegroundWindow() == bar_hwnd`, not an internal
`is_expanded` boolean. A flag can desynchronise from reality; the question that
actually matters is where the user's keystrokes are going, and only the OS
knows. The same test governs foreground restoration (§4.4), so one fact answers
both.

A consequence that falls out for free: if the user clicks into their application
while the panel is open, the bar simply stops being foreground and suppression
lifts on its own. Nothing is destroyed, nothing is forced, no event handler is
needed.

### 4.3 How this accommodates voice later, with no rework

A mic button would be a **control, not a focus target** — same class as Stop.
If it took focus itself, clicking it would suppress ESC and SPACE without giving
the user a cursor: a dead state where keys do nothing and the tour's shortcuts
are off. Instead a mic press would focus the text box, because that is where its
output lands, and suppression then follows from the existing rule. Recorded here
so the later milestone inherits a decision rather than re-opening this one.

### 4.4 Foreground restoration, and what happens when it fails

Opening the panel takes focus away from the application being taught. Menus may
close; some applications change appearance when deactivated. Closing the panel
should hand focus back.

**The governing principle: aggressive focus restoration is itself a form of
acting for the user.** D006 says the system shows and never acts. An application
that yanks focus back is doing something nobody asked for. So restoration is
best-effort, attempted **once**, never retried, never forced.

**Why the attempt should normally succeed.** `SetForegroundWindow` is refused by
Windows' foreground lock for a process that is not already frontmost — measured
in this repo during the wrong-action milestone, where it broke a whole set of
tests under pytest (`docs/superpowers/plans/2026-08-20-wrong-action-feedback.md`,
Task 1, records the failure and the rewrite it forced). Here the asymmetry works
for us: at the moment the panel closes **we are** the foreground process, and
Windows permits the foreground process to give focus away.

**Which window.** Re-resolve with `first_matching_hwnd(title_re)` at close time
rather than caching the handle from open time. If the target closed and reopened
while the user typed, the cached handle is dead and the re-resolved one is
right. It is the same function warm-up depends on, so both agree on what "the
target" means.

| Case | Behaviour |
|---|---|
| User moved to a third application while typing | **Do nothing.** Guarded by `GetForegroundWindow() == bar_hwnd` before restoring. If the user has moved on, taking focus back is the worst available response. |
| Target gone (`first_matching_hwnd` returns 0) | Nothing to restore; status says the target is not visible. The tour's existing absent-window and staleness handling covers its side. No new state. |
| Target minimised | **Do not un-minimise.** `windows_matching` already excludes minimised windows so it reads as absent. Restoring a window the user minimised is acting for them. |
| `SetForegroundWindow` returns 0 or raises | Accept once, silently. No retry, no `AttachThreadInput`. The user's next click settles focus anyway, and fighting the OS here is how focus-stealing bugs are born. |

**The invariant is "we never fight for focus", not "focus ends up on the
target".** The second cannot be guaranteed without behaving badly.

## 5. What the bar shows and captures

Collapsed, one status line built only from state that already exists —
`tour.step_index`, `len(recipe.steps)`, and the state machine's current state.
No new state is invented for display.

On submit, the text becomes the tour's stated goal, shown in the bar and printed
once to the console.

**Held in memory for the session only.** The knowledge base is entity-scoped to
`(user_id, app_id, concept)` and stores what grounding *learned* — AutomationIds
and control types. A typed goal is neither, and persisting it would mean schema
work for something nothing yet reads. It goes no further until the inference
milestone gives it a consumer.

## 6. Safety

This bar is introduced *as* a safety improvement, so its own failure modes matter
more than its features.

**Stop is always mouse-clickable, in both states, regardless of focus.** That is
what makes suppressing ESC while typing acceptable at all.

**The bar must never be required for escape.** If window creation fails, the
tour runs anyway, ESC still works, and the failure is printed. A bar that fails
to appear degrades to exactly today's behaviour — never to a full-screen
click-through overlay with no way out. This is why "retire global polling and
let the bar own all input" was rejected: it would make the safety hatch depend
on the newest, least-proven window in the system.

**ESC always does something, in every state.** Collapsed it quits the tour, as
today. With the panel focused it closes the panel, and the next press quits.
There is no state in which pressing ESC is inert — which matters because ESC is
what a user reaches for when something has gone wrong and they want out.

**Pause stops ticking and nothing else.** The pump keeps running, ESC keeps
polling, the perception worker keeps walking. Skipping `tour.tick()` means no
renderer writes occur, so the last ring stays exactly as drawn — consistent with
D027, since zero ticks is zero writes.

## 7. Testing

The overlay's existing harnesses assert real Win32 state and screen pixels
rather than appearance, and this work is squarely that kind.

- **Styles are the deliberate inverse.** Assert `WS_EX_TRANSPARENT` and
  `WS_EX_NOACTIVATE` are ABSENT on the bar and still PRESENT on the overlay.
  The second half is the regression guard: it catches a refactor that unified
  the two windows' creation and quietly made the overlay focusable.
- Both windows coexist, and the overlay is still click-through with the bar up.
- **Suppression, the safety-critical one.** With the panel focused, a simulated
  SPACE does not advance the step; collapsed, it does. **Mutation-verify by
  deleting the suppression check** — the test must fail. A silent regression here
  means typing confirms steps and nothing notices.
- **Degradation.** Bar creation failure leaves ESC working and the tour running.
- **Pause** as an ordered-sequence test on an injected clock (D026): ticks stop,
  ESC polling continues. Not an end-state assertion — "it eventually stopped" is
  true of a crash.
- Every claim above that names a behaviour gets a mutation (D018), and each test
  states the property it protects and whether its invariant implies it (D031).

## 8. What this design does not establish

- **No second window has ever coexisted with the overlay in this codebase.**
  Z-order between two topmost windows, and click routing past a full-screen
  click-through window, are reasoned from documented Win32 behaviour here, not
  measured. The first task should prove the two windows coexist before anything
  is built on top of that assumption.
- The `SetForegroundWindow` asymmetry (refused when not frontmost, permitted
  when frontmost) is documented Windows behaviour and the refusal half was
  measured here; **the permitted half has not been tested in this repo.**
- Multi-monitor placement of the bar is unspecified beyond "edge-positioned".
  The overlay spans the whole virtual desktop via `dpi.virtual_screen_rect()`;
  which monitor the bar should sit on is not decided.
- Nothing here measures whether a visible Stop button actually gets used in
  preference to ESC. The safety argument is that an invisible escape cannot be
  relied upon, not that this one demonstrably is.
