# Perception Off the UI Thread Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the UI thread responsive — ESC always live, overlay always dismissable — no matter how slow perception becomes.

**Architecture:** A `PerceptionService` worker thread continuously observes the target and publishes its latest timestamped result into a single overwrite slot. The UI thread reads that slot without ever blocking. `GuidedTour` keeps its current collaborator shape and gains staleness handling, so every existing fake keeps working. A staged staleness ladder decides what the overlay shows while observations age.

**Tech Stack:** Python 3.12, `threading`, `pywin32` (`win32gui`/`win32api`/`pythoncom`), `pywinauto` (UIA), pytest 9.0.3.

**Spec:** `docs/superpowers/specs/2026-08-14-perception-off-the-ui-thread-design.md`

## Global Constraints

- **D006 — the system never acts.** No `SendInput`, `mouse_event`, PyAutoGUI, synthesised keystrokes, or moving the real cursor, anywhere, including tests.
- **The overlay is always escapable.** ESC polled from any application, plus `--seconds`, plus teardown in `finally`. The UI thread must keep pumping messages regardless of perception.
- **The collaborator contract keeps its current shape.** `snapshotter()` and `grounder(step, index, elements)` still get called and still return values. **All 134 existing pytest tests must keep passing unchanged** — if a fake needs editing, the contract was not preserved.
- **Only frozen dataclasses of primitives cross the thread boundary.** `Element`, `Snapshot`, `Observation`. No COM object ever does; the worker owns its own `Desktop()`.
- **"Confirmed-fresh" = the walk completed without raising**, regardless of how many elements it found.
- **`observed_at == 0.0` means untimestamped and is treated as fresh** — that is what a synchronous or faked perception is.
- **Import `ghostcursor.overlay.dpi` before creating any window.**
- Existing pixel harnesses keep their own runner and must keep passing: `python -m tests.test_overlay` (14/14), `python -m tests.test_end_to_end` (8/8). Never run them alongside other work.

## File Structure

| File | Responsibility |
|---|---|
| `tests/hung_window.py` | Child script: creates a window then stops pumping. The fixture everything else needs |
| `ghostcursor/reasoning/verification.py` | *(modify)* `Snapshot` gains `observed_at`; `take_snapshot` accepts pre-fetched elements |
| `ghostcursor/reasoning/loop.py` | *(modify)* `AWAITING` only verifies against a strictly newer observation |
| `ghostcursor/reasoning/staleness.py` | The display ladder: age → `Freshness`, debounced |
| `ghostcursor/overlay/window.py` | *(modify)* `set_hint` gains a freshness argument; dimmed ring |
| `ghostcursor/perception/service.py` | `PerceptionService`: worker, slot, timestamp, heartbeat, health |
| `ghostcursor/run.py` | *(modify)* wire the service, staleness → renderer, health policy |

**Test runner:** pytest for everything new. Never run the two pixel harnesses from a task.

---

### Task 1: The hung-window harness

Everything else is tested against this. Build it first — without it, the failure this whole plan addresses cannot be reproduced.

**Files:**
- Create: `tests/hung_window.py`
- Test: `tests/test_hung_window.py`

**Interfaces:**
- Produces:
  - `tests/hung_window.py` — run as `python -B tests/hung_window.py <title>`; prints `ready` on stdout once its window exists, then never pumps messages again
  - `HungWindow(title="GhostCursorHungApp")` context manager in `tests/test_hung_window.py`'s module — starts the child, waits for `ready`, kills it on exit

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hung_window.py
"""A target window whose owner has stopped pumping messages.

This reproduces the failure the whole threading change exists for: an
ordinary "Not Responding" application. A cheap EnumWindows check still sees
the window, but a UIA tree walk against it blocks for ~40 seconds on first
contact and ~10 seconds after — 80x the 0.5s tick ceiling, with no timeout
available to tune.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHILD = REPO / "tests" / "hung_window.py"


class HungWindow:
    """Runs a child process that shows a window and then stops pumping."""

    def __init__(self, title: str = "GhostCursorHungApp") -> None:
        self.title = title
        self.title_re = f".*{title}.*"
        self._child: subprocess.Popen | None = None

    def __enter__(self) -> "HungWindow":
        self._child = subprocess.Popen(
            [sys.executable, "-B", str(CHILD), self.title],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(REPO), env=dict(os.environ, PYTHONPATH=str(REPO)),
        )
        line = self._child.stdout.readline().strip()
        assert line == "ready", f"child did not start: {line!r}"
        time.sleep(0.3)  # let the window settle
        return self

    def __exit__(self, *exc) -> None:
        if self._child:
            self._child.kill()
            self._child.wait(timeout=30)


def test_the_cheap_existence_check_still_sees_a_hung_window():
    """This is why the fast path cannot protect against a hung app."""
    from ghostcursor.perception.uia import windows_matching

    with HungWindow() as hung:
        assert windows_matching(hung.title_re), (
            "the hung window is invisible to EnumWindows, so this fixture "
            "is not reproducing the real failure"
        )


def test_a_uia_walk_against_a_hung_window_blocks_far_past_the_tick_ceiling():
    """The measurement that justifies the whole change."""
    from ghostcursor.perception.uia import iter_elements

    with HungWindow() as hung:
        start = time.perf_counter()
        iter_elements(hung.title_re)
        elapsed = time.perf_counter() - start

    assert elapsed > 2.0, (
        f"the walk took only {elapsed:.2f}s — the fixture is not actually "
        "hanging, so every test built on it proves nothing"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_hung_window.py -v`
Expected: FAIL — `tests/hung_window.py` does not exist, so the child cannot start.

- [ ] **Step 3: Write the child script**

```python
# tests/hung_window.py
"""A window whose owner deliberately stops pumping messages.

Used as a test fixture: this is what an ordinary "Not Responding" application
looks like to UIA. Creating the window requires a pump; after that we stop,
which is precisely the state that makes a UIA tree walk block for tens of
seconds.

Prints `ready` once the window exists so the parent can synchronise, then
sleeps without servicing its message queue until killed.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.uia_app import SyntheticApp


def main() -> int:
    title = sys.argv[1] if len(sys.argv) > 1 else "GhostCursorHungApp"
    app = SyntheticApp(title=title)
    app.__enter__()
    print("ready", flush=True)
    # Deliberately never pump again. The parent kills this process.
    time.sleep(600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -B -m pytest tests/test_hung_window.py -v`
Expected: 2 passed. The second test takes ~40s — that is the point of it.

- [ ] **Step 5: Commit**

```bash
git add tests/hung_window.py tests/test_hung_window.py
git commit -m "test: add a hung-window harness that reproduces the 40s UIA block"
```

---

### Task 2: Timestamped observations and the freshness gate

The correctness detail from spec §6. Do it before the service exists, so the rule is in place when async observations arrive.

**Files:**
- Modify: `ghostcursor/reasoning/verification.py`
- Modify: `ghostcursor/reasoning/loop.py`
- Test: `tests/test_freshness_gate.py`

**Interfaces:**
- Produces:
  - `Snapshot(title, elements, focused_automation_id="", observed_at=0.0)`
  - `take_snapshot(title_re, elements=None, observed_at=0.0) -> Snapshot`
  - `GuidedTour` in `AWAITING_USER_ACTION` verifies only against an observation strictly newer than `_before`, unless either is untimestamped

- [ ] **Step 1: Write the failing test**

```python
# tests/test_freshness_gate.py
"""AWAITING_USER_ACTION must never verify against a stale observation.

With perception published into a slot, AWAITING can read back the SAME
observation OBSERVING used. Verification would then compare a state against
itself, conclude "nothing changed" forever, and every tour would stall on its
first step — the exact failure D019 warns about, reintroduced by the move to
a worker thread.

An untimestamped snapshot (observed_at == 0.0) is treated as fresh: that is
what a synchronous or faked perception is, and it keeps every existing fake
working.
"""

from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.loop import GuidedTour, State
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor, Recipe, Risk, Step, TargetDescriptor,
    UserAction, VerificationKind, VerificationRule,
)
from ghostcursor.reasoning.verification import Snapshot

TARGET = GroundedTarget((10, 10, 110, 40), 1, "1001", "Button", "Export")
EXPORT = Element("Export", "Button", "1001", (10, 10, 110, 40))


class FakeRenderer:
    def __init__(self):
        self.shown, self.cleared = [], 0

    def show(self, grounded, instruction_text):
        self.shown.append(instruction_text)

    def clear(self):
        self.cleared += 1


def _recipe():
    return Recipe(app_id="t", intent="i", steps=[Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(
            kind=VerificationKind.ELEMENT_APPEARS,
            args={"target_descriptor": {"name": "Saved"}},
        ),
        risk=Risk.NORMAL,
    )])


def _tour(snapshots, verifier):
    seq = iter(snapshots)
    last = {"s": snapshots[-1]}

    def snapshotter():
        try:
            last["s"] = next(seq)
        except StopIteration:
            pass
        return last["s"]

    return GuidedTour(
        recipe=_recipe(),
        grounder=lambda step, i, elements=None: TARGET,
        snapshotter=snapshotter,
        verifier=verifier,
        renderer=FakeRenderer(),
        clock=lambda: 0.0,
    )


def test_a_stale_observation_is_not_verified_against():
    """The slot has not advanced: this is NO verification attempt, not a
    failed one."""
    stale = Snapshot("App", (EXPORT,), observed_at=100.0)
    calls = []

    def verifier(rule, before, after):
        calls.append((before.observed_at, after.observed_at))
        return True  # would advance if it were ever consulted

    tour = _tour([stale, stale, stale, stale, stale, stale], verifier)
    for _ in range(6):
        tour.tick()

    assert calls == [], "verification ran against an observation no newer than _before"
    assert tour.step_index == 0
    assert tour.state is State.AWAITING_USER_ACTION


def test_a_newer_observation_is_verified_against():
    before = Snapshot("App", (EXPORT,), observed_at=100.0)
    newer = Snapshot("App", (EXPORT,), observed_at=100.5)
    calls = []

    def verifier(rule, b, a):
        calls.append((b.observed_at, a.observed_at))
        return True

    tour = _tour([before, before, before, before, newer, newer], verifier)
    for _ in range(6):
        tour.tick()

    assert calls, "a strictly newer observation was not verified against"
    assert tour.step_index == 1


def test_untimestamped_snapshots_are_treated_as_fresh():
    """Every existing fake returns the same untimestamped Snapshot forever.
    Those must keep verifying, or the collaborator contract was not preserved.
    """
    still = Snapshot("App", (EXPORT,))  # observed_at defaults to 0.0
    calls = []

    def verifier(rule, before, after):
        calls.append(1)
        return True

    tour = _tour([still] * 6, verifier)
    for _ in range(6):
        tour.tick()

    assert calls, "untimestamped snapshots were gated as stale"
    assert tour.step_index == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_freshness_gate.py -v`
Expected: FAIL — `Snapshot` has no `observed_at`, so the first two tests error on the keyword argument.

- [ ] **Step 3: Add the field and the gate**

In `ghostcursor/reasoning/verification.py`, add the field to `Snapshot` (a defaulted field keeps positional construction like `Snapshot("App", ())` working):

```python
@dataclass(frozen=True)
class Snapshot:
    title: str
    elements: tuple[Element, ...]
    focused_automation_id: str = ""
    #: When the worker completed the walk that produced this, from the
    #: service's clock. 0.0 means untimestamped — a synchronous or faked
    #: perception — and is treated as always fresh.
    observed_at: float = 0.0
```

And let `take_snapshot` reuse an already-walked element list:

```python
def take_snapshot(
    title_re: str,
    elements: list[Element] | tuple[Element, ...] | None = None,
    observed_at: float = 0.0,
) -> Snapshot:
    import win32gui

    if elements is None:
        elements = iter_elements(title_re)
    try:
        title = win32gui.GetWindowText(win32gui.GetForegroundWindow())
    except Exception:
        title = ""
    return Snapshot(
        title=title,
        elements=_sort_elements(elements),
        focused_automation_id="",
        observed_at=observed_at,
    )
```

In `ghostcursor/reasoning/loop.py`, add the helper and use it in `AWAITING_USER_ACTION`:

```python
def _is_newer(after: Snapshot, before: Snapshot | None) -> bool:
    """Whether `after` describes a genuinely later moment than `before`.

    An untimestamped snapshot (0.0) is treated as fresh: that is what a
    synchronous or faked perception is, and gating those would break every
    existing collaborator fake.
    """
    if before is None or after.observed_at == 0.0 or before.observed_at == 0.0:
        return True
    return after.observed_at > before.observed_at
```

Then in the `AWAITING_USER_ACTION` branch, guard the verification:

```python
        elif self.state is State.AWAITING_USER_ACTION:
            step = self.current_step
            after = self.snapshotter()

            # A slot that has not advanced is NO verification attempt, not a
            # failed one. Verifying against the same observation OBSERVING
            # used would compare a state against itself, so the rule would
            # never fire and the tour would stall on this step forever.
            if not _is_newer(after, self._before):
                return self.state

            if step.verification_rule.kind is VerificationKind.USER_CONFIRMS:
                satisfied = self._confirmed
            else:
                satisfied = self.verifier(step.verification_rule, self._before, after)
```

Note: the `return self.state` keeps the idle/re-hint clock running on later ticks, because `_waiting_since` is untouched — the tour is still waiting for the user, it simply has nothing new to judge.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -B -m pytest tests/test_freshness_gate.py tests/test_loop.py tests/test_verification.py -v`
Expected: all pass, including every pre-existing loop test unchanged.

- [ ] **Step 5: Confirm the whole suite still passes, then commit**

```bash
python -B -m pytest tests/ -q
git add ghostcursor/reasoning/verification.py ghostcursor/reasoning/loop.py tests/test_freshness_gate.py
git commit -m "feat: gate verification on a strictly newer observation"
```

---

### Task 3: The staleness ladder

Pure logic, no threads, no UI. Test it with an injected clock.

**Files:**
- Create: `ghostcursor/reasoning/staleness.py`
- Test: `tests/test_staleness.py`

**Interfaces:**
- Produces:
  - `Freshness` enum: `FRESH`, `DIMMED`, `HIDDEN`
  - `StalenessLadder(clock, dim_after_s=1.5, hide_after_s=5.0, recover_after=3)`
  - `.observed()` — record a confirmed-fresh observation
  - `.freshness() -> Freshness`
  - `.age() -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_staleness.py
"""What the overlay shows while observations age.

Staged rather than one policy for the whole freeze: a hint unchanged through
ordinary tick jitter, visibly dimmed once it is merely "last known", and gone
once the odds the UI has actually changed outweigh the value of showing it.

Recovery is debounced so a flaky, not-fully-hung app cannot flicker.
"""

from ghostcursor.reasoning.staleness import Freshness, StalenessLadder


def _ladder(now):
    return StalenessLadder(clock=lambda: now["t"])


def test_a_fresh_observation_shows_the_hint_unchanged():
    now = {"t": 0.0}
    ladder = _ladder(now)
    ladder.observed()
    assert ladder.freshness() is Freshness.FRESH


def test_ordinary_tick_jitter_does_not_dim_the_hint():
    now = {"t": 0.0}
    ladder = _ladder(now)
    ladder.observed()
    now["t"] = 1.4
    assert ladder.freshness() is Freshness.FRESH


def test_the_hint_dims_once_it_is_merely_last_known():
    now = {"t": 0.0}
    ladder = _ladder(now)
    ladder.observed()
    now["t"] = 1.6
    assert ladder.freshness() is Freshness.DIMMED


def test_the_hint_is_hidden_once_it_is_probably_wrong():
    now = {"t": 0.0}
    ladder = _ladder(now)
    ladder.observed()
    now["t"] = 5.1
    assert ladder.freshness() is Freshness.HIDDEN


def test_with_no_observation_yet_the_hint_is_hidden():
    """Nothing has been seen, so there is nothing to justify showing."""
    assert _ladder({"t": 0.0}).freshness() is Freshness.HIDDEN


def test_one_lucky_observation_does_not_restore_a_hidden_hint():
    """Recovery is debounced: a flaky app must not flicker."""
    now = {"t": 0.0}
    ladder = _ladder(now)
    ladder.observed()
    now["t"] = 6.0
    assert ladder.freshness() is Freshness.HIDDEN

    ladder.observed()
    assert ladder.freshness() is Freshness.HIDDEN, "one observation restored the hint"


def test_a_debounced_run_of_observations_restores_the_hint():
    now = {"t": 0.0}
    ladder = _ladder(now)
    ladder.observed()
    now["t"] = 6.0
    ladder.observed()
    ladder.observed()
    ladder.observed()
    assert ladder.freshness() is Freshness.FRESH


def test_a_failed_observation_breaks_the_recovery_run():
    now = {"t": 0.0}
    ladder = _ladder(now)
    ladder.observed()
    now["t"] = 6.0
    ladder.observed()
    ladder.observed()
    now["t"] = 12.0          # time passes with no observation: run is broken
    ladder.observed()
    assert ladder.freshness() is Freshness.HIDDEN


def test_age_reports_time_since_the_last_observation():
    now = {"t": 10.0}
    ladder = _ladder(now)
    ladder.observed()
    now["t"] = 12.5
    assert ladder.age() == 2.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_staleness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.reasoning.staleness'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/reasoning/staleness.py
"""How old an observation may get before the overlay stops trusting it.

Staged rather than a single policy, because the honest answer changes with
age: through ordinary tick jitter the hint is still right; a little later it
is "last known, unconfirmed"; later still the odds the UI has actually moved
outweigh the value of showing a ring at all.

Measured from the last CONFIRMED-FRESH observation — a walk that completed
without raising, however many elements it found — and never reset by a single
lucky observation, so a flaky application cannot flicker between states.
"""

from __future__ import annotations

import time
from enum import Enum, auto
from typing import Callable

DEFAULT_DIM_AFTER_S = 1.5
DEFAULT_HIDE_AFTER_S = 5.0
#: Consecutive observations required to leave HIDDEN. One is not enough: a
#: half-hung app that answers occasionally would otherwise blink the hint.
DEFAULT_RECOVER_AFTER = 3


class Freshness(Enum):
    FRESH = auto()   # draw the hint normally
    DIMMED = auto()  # draw it, visibly unconfirmed
    HIDDEN = auto()  # draw nothing


class StalenessLadder:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        dim_after_s: float = DEFAULT_DIM_AFTER_S,
        hide_after_s: float = DEFAULT_HIDE_AFTER_S,
        recover_after: int = DEFAULT_RECOVER_AFTER,
    ) -> None:
        self.clock = clock
        self.dim_after_s = dim_after_s
        self.hide_after_s = hide_after_s
        self.recover_after = recover_after
        self._last_seen: float | None = None
        self._streak = 0
        self._hidden = True  # nothing observed yet

    def observed(self) -> None:
        """Record a confirmed-fresh observation."""
        now = self.clock()
        if self._last_seen is not None and now - self._last_seen > self.hide_after_s:
            self._streak = 0  # the gap broke any recovery run
        self._last_seen = now
        self._streak += 1
        if self._hidden and self._streak >= self.recover_after:
            self._hidden = False

    def age(self) -> float:
        if self._last_seen is None:
            return float("inf")
        return self.clock() - self._last_seen

    def freshness(self) -> Freshness:
        age = self.age()
        if age > self.hide_after_s:
            self._hidden = True
            self._streak = 0
            return Freshness.HIDDEN
        if self._hidden:
            return Freshness.HIDDEN
        if age > self.dim_after_s:
            return Freshness.DIMMED
        return Freshness.FRESH
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_staleness.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/reasoning/staleness.py tests/test_staleness.py
git commit -m "feat: add the staged staleness ladder"
```

---

### Task 4: A dimmed hint in the overlay

**Files:**
- Modify: `ghostcursor/overlay/window.py`
- Test: `tests/test_overlay_freshness.py`

**Interfaces:**
- Consumes: `staleness.Freshness`
- Produces: `set_hint(hwnd, screen_x, screen_y, radius=24, freshness=Freshness.FRESH)`; `DIMMED_RING_COLOR`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_overlay_freshness.py
"""The overlay must be able to say "this hint is unconfirmed".

Colour, not disappearance: the user keeps their guidance while being told it
may no longer be current.
"""

from ghostcursor.overlay import window as ov
from ghostcursor.reasoning.staleness import Freshness


def test_a_dimmed_hint_uses_a_different_colour_from_a_fresh_one():
    assert ov.DIMMED_RING_COLOR != ov.RING_COLOR


def test_set_hint_records_the_requested_freshness():
    ov._hint = None
    hwnd = ov.create_overlay_window()
    try:
        ov.set_hint(hwnd, 300, 300, freshness=Freshness.DIMMED)
        assert ov._hint is not None
        assert ov._hint[3] is Freshness.DIMMED
        ov.set_hint(hwnd, 300, 300)
        assert ov._hint[3] is Freshness.FRESH, "freshness must default to FRESH"
    finally:
        ov.destroy_overlay_window(hwnd)


def test_hiding_clears_the_hint_entirely():
    hwnd = ov.create_overlay_window()
    try:
        ov.set_hint(hwnd, 300, 300)
        ov.clear_hint(hwnd)
        assert ov._hint is None
    finally:
        ov.destroy_overlay_window(hwnd)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_overlay_freshness.py -v`
Expected: FAIL — `DIMMED_RING_COLOR` does not exist.

- [ ] **Step 3: Write minimal implementation**

In `ghostcursor/overlay/window.py`, add the colour beside the existing one:

```python
RING_COLOR = win32api.RGB(0, 200, 255)
#: A hint we can no longer confirm. Same ring, visibly muted — the user keeps
#: their guidance and can see it may be out of date (see reasoning/staleness).
DIMMED_RING_COLOR = win32api.RGB(0, 90, 115)
```

Store freshness with the hint and use it when painting:

```python
def set_hint(
    hwnd: int,
    screen_x: int,
    screen_y: int,
    radius: int = 24,
    freshness: "Freshness" = None,
) -> None:
    """Show the hint ring centred on a *screen* coordinate, repainting now."""
    from ghostcursor.reasoning.staleness import Freshness

    global _hint
    if freshness is None:
        freshness = Freshness.FRESH
    _hint = (screen_x - _origin[0], screen_y - _origin[1], radius, freshness)
    win32gui.InvalidateRect(hwnd, None, False)
    win32gui.UpdateWindow(hwnd)
```

And in the paint path, unpack the fourth element and pick the colour:

```python
def _paint_ring(hdc, x: int, y: int, radius: int, freshness) -> None:
    from ghostcursor.reasoning.staleness import Freshness

    colour = RING_COLOR if freshness is Freshness.FRESH else DIMMED_RING_COLOR
    pen = win32gui.CreatePen(win32con.PS_SOLID, RING_THICKNESS, colour)
    old_pen = win32gui.SelectObject(hdc, pen)
    old_brush = win32gui.SelectObject(hdc, win32gui.GetStockObject(win32con.NULL_BRUSH))
    win32gui.Ellipse(hdc, x - radius, y - radius, x + radius, y + radius)
    win32gui.SelectObject(hdc, old_brush)
    win32gui.SelectObject(hdc, old_pen)
    win32gui.DeleteObject(pen)
```

The `WM_PAINT` handler already calls `_paint_ring(hdc, *_hint)`; the extra tuple element flows through unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -B -m pytest tests/test_overlay_freshness.py -v`
Expected: 3 passed

- [ ] **Step 5: Verify the pixel harnesses still pass and commit**

The pixel harnesses assert on ring colour, so this task can break them. Ask the controller to run them, or run them yourself ONLY if nothing else is running:

```bash
python -B -m tests.test_overlay
python -B -m tests.test_end_to_end
git add ghostcursor/overlay/window.py tests/test_overlay_freshness.py
git commit -m "feat: add a dimmed ring for unconfirmed hints"
```

---

### Task 5: The perception service

**Files:**
- Create: `ghostcursor/perception/service.py`
- Test: `tests/test_perception_service.py`

**Interfaces:**
- Consumes: `uia.iter_elements`, `verification.take_snapshot`, `verification.Snapshot`
- Produces:
  - `Observation(snapshot, elements, observed_at, ok)` — frozen dataclass
  - `PerceptionService(title_re, walker=iter_elements, clock=time.monotonic, interval_s=0.2)`
  - `.start()`, `.stop()`, `.latest() -> Observation | None`, `.is_alive() -> bool`, `.heartbeat -> int`, `.restarts -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_perception_service.py
"""Perception runs on a worker thread and publishes into a single slot.

The UI thread must never block on it, however slow the target is.
"""

import threading
import time

from ghostcursor.perception.service import Observation, PerceptionService
from ghostcursor.perception.uia import Element

EXPORT = Element("Export", "Button", "1001", (10, 10, 110, 40))


def _service(walker, **kw):
    return PerceptionService(title_re=".*Whatever.*", walker=walker, interval_s=0.01, **kw)


def test_latest_is_none_before_anything_has_been_observed():
    service = _service(lambda t: [EXPORT])
    assert service.latest() is None


def test_the_worker_publishes_observations():
    service = _service(lambda t: [EXPORT])
    service.start()
    try:
        deadline = time.monotonic() + 5
        while service.latest() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        observation = service.latest()
    finally:
        service.stop()

    assert observation is not None
    assert observation.ok is True
    assert observation.elements == (EXPORT,)
    assert observation.observed_at > 0


def test_the_slot_holds_only_the_newest_observation():
    counter = {"n": 0}

    def walker(title_re):
        counter["n"] += 1
        return [Element(f"E{counter['n']}", "Button", str(counter["n"]), (0, 0, 5, 5))]

    service = _service(walker)
    service.start()
    try:
        deadline = time.monotonic() + 5
        while counter["n"] < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        first = service.latest()
        time.sleep(0.1)
        second = service.latest()
    finally:
        service.stop()

    assert second.observed_at >= first.observed_at
    assert len(second.elements) == 1, "the slot accumulated instead of overwriting"


def test_an_empty_result_still_counts_as_a_successful_observation():
    """Spec: confirmed-fresh means the walk completed, not that it found
    anything. A legitimately empty window must not look frozen."""
    service = _service(lambda t: [])
    service.start()
    try:
        deadline = time.monotonic() + 5
        while service.latest() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        observation = service.latest()
    finally:
        service.stop()

    assert observation is not None
    assert observation.ok is True
    assert observation.elements == ()


def test_a_raising_walker_does_not_kill_the_worker():
    """A transient perception error must not end perception for the run."""
    calls = {"n": 0}

    def walker(title_re):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return [EXPORT]

    service = _service(walker)
    service.start()
    try:
        deadline = time.monotonic() + 5
        while service.latest() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        observation = service.latest()
        alive = service.is_alive()
    finally:
        service.stop()

    assert observation is not None, "the worker gave up after a transient error"
    assert alive


def test_the_heartbeat_advances_even_while_every_walk_fails():
    """Distinguishes 'looping through failures' from 'blocked in a call'."""
    def walker(title_re):
        raise RuntimeError("always fails")

    service = _service(walker)
    service.start()
    try:
        time.sleep(0.2)
        beats = service.heartbeat
        assert service.latest() is None, "a failed walk must not publish"
    finally:
        service.stop()

    assert beats > 0


def test_stop_ends_the_worker_thread():
    service = _service(lambda t: [EXPORT])
    service.start()
    service.stop()
    assert not service.is_alive()


def test_the_ui_thread_is_never_blocked_by_a_slow_walk():
    """The property this whole change exists for."""
    started = threading.Event()

    def slow_walker(title_re):
        started.set()
        time.sleep(3.0)
        return [EXPORT]

    service = _service(slow_walker)
    service.start()
    try:
        assert started.wait(timeout=5)
        # The caller reads the slot repeatedly while the worker is stuck.
        t0 = time.perf_counter()
        for _ in range(50):
            service.latest()
        elapsed = time.perf_counter() - t0
    finally:
        service.stop()

    assert elapsed < 0.5, (
        f"50 slot reads took {elapsed:.2f}s while the worker was blocked — "
        "the UI thread is still coupled to perception"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_perception_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.perception.service'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/perception/service.py
"""Perception on a worker thread, published into a single slot.

The UI thread owns the overlay window and must never block: ESC is polled
between ticks, so any blocking call there is time the user cannot dismiss a
window covering their screen. A UIA walk against an application that has
stopped pumping messages blocks for ~40s on first contact and ~10s after,
with no timeout available to tune — so the walk cannot happen on the UI
thread at all.

A single slot, not a queue: a queue drained to "newest, discard the rest" is
a depth-1 buffer with extra ceremony. Overwrite IS the discard.

Every published observation carries a timestamp. That is what lets the
staleness ladder compute an age, and what lets the loop tell a genuinely
later observation from the one it already judged.

COM: the worker calls CoInitializeEx and owns its own UIA access. UIA objects
are apartment-bound, so only frozen dataclasses of primitives ever cross the
thread boundary — Element, Snapshot, Observation. No COM object does.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from ghostcursor.perception.uia import Element, iter_elements
from ghostcursor.reasoning.verification import Snapshot, take_snapshot

DEFAULT_INTERVAL_S = 0.2


@dataclass(frozen=True)
class Observation:
    """One completed look at the target. Crosses the thread boundary, so
    every field is a primitive or a frozen dataclass of primitives."""

    snapshot: Snapshot
    elements: tuple[Element, ...]
    observed_at: float
    ok: bool


class PerceptionService:
    def __init__(
        self,
        title_re: str,
        walker: Callable[[str], list[Element]] = iter_elements,
        clock: Callable[[], float] = time.monotonic,
        interval_s: float = DEFAULT_INTERVAL_S,
    ) -> None:
        self.title_re = title_re
        self.walker = walker
        self.clock = clock
        #: Throttle. Perception costs ~26ms against a 250ms tick, so an
        #: unthrottled loop would spin ~10x faster than anything consumes.
        self.interval_s = interval_s

        self.heartbeat = 0
        self.restarts = 0
        self._slot: Observation | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="ghostcursor-perception", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            # A worker blocked in UIA cannot be interrupted; it is a daemon
            # thread and will exit with the process. Waiting briefly is
            # enough for the common case.
            self._thread.join(timeout=timeout)

    def restart(self) -> None:
        """Replace a worker that has died. Callers decide the policy."""
        self.stop()
        self.restarts += 1
        self.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- the slot ----------------------------------------------------------
    def latest(self) -> Observation | None:
        """The most recent observation, or None if there is not one yet.
        Never blocks."""
        with self._lock:
            return self._slot

    def _publish(self, observation: Observation) -> None:
        with self._lock:
            self._slot = observation

    # -- worker ------------------------------------------------------------
    def _run(self) -> None:
        try:
            import pythoncom

            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        except Exception:
            # Without COM this worker cannot observe anything, but it must
            # not die silently — it keeps looping and the staleness ladder
            # reports the resulting absence of observations.
            pass

        try:
            while not self._stop.is_set():
                self.heartbeat += 1
                try:
                    elements = tuple(self.walker(self.title_re))
                    observed_at = self.clock()
                    snapshot = take_snapshot(
                        self.title_re, elements=elements, observed_at=observed_at
                    )
                    self._publish(
                        Observation(
                            snapshot=snapshot,
                            elements=elements,
                            observed_at=observed_at,
                            ok=True,
                        )
                    )
                except Exception:
                    # A failed walk publishes nothing: the previous
                    # observation simply keeps ageing, which is exactly what
                    # the staleness ladder is for. The heartbeat still
                    # advances, so "looping through failures" stays
                    # distinguishable from "blocked in a call".
                    pass
                self._stop.wait(self.interval_s)
        finally:
            try:
                import pythoncom

                pythoncom.CoUninitialize()
            except Exception:
                pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -B -m pytest tests/test_perception_service.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/perception/service.py tests/test_perception_service.py
git commit -m "feat: run perception on a worker thread with a published slot"
```

---

### Task 6: Worker health policy

**Files:**
- Create: `ghostcursor/perception/health.py`
- Test: `tests/test_worker_health.py`

**Interfaces:**
- Consumes: `PerceptionService`, `StalenessLadder`
- Produces:
  - `WorkerHealth(service, ladder, dead_after_s=15.0, log=print)`
  - `.check() -> str | None` — returns a failure reason when the tour should end, else `None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worker_health.py
"""A dead-but-undetected worker would be a regression dressed as a fix.

The UI thread stays responsive and ESC still works, so nothing looks wrong
while the system silently stops guiding — harder to notice than a freeze, not
easier.
"""

from ghostcursor.perception.health import WorkerHealth
from ghostcursor.reasoning.staleness import StalenessLadder


class FakeService:
    def __init__(self, alive=True):
        self._alive = alive
        self.heartbeat = 7
        self.restarts = 0
        self.started = 0

    def is_alive(self):
        return self._alive

    def restart(self):
        self.restarts += 1
        self.started += 1
        self._alive = True


def _health(service, now, **kw):
    ladder = StalenessLadder(clock=lambda: now["t"])
    return WorkerHealth(service=service, ladder=ladder, log=lambda m: logs.append(m), **kw), ladder


logs: list[str] = []


def setup_function():
    logs.clear()


def test_a_healthy_worker_reports_nothing():
    now = {"t": 0.0}
    service = FakeService()
    health, ladder = _health(service, now)
    ladder.observed()
    assert health.check() is None
    assert service.restarts == 0


def test_a_dead_worker_is_restarted_once():
    now = {"t": 0.0}
    service = FakeService(alive=False)
    health, ladder = _health(service, now)
    ladder.observed()

    assert health.check() is None, "the first death should restart, not give up"
    assert service.restarts == 1


def test_a_second_death_ends_the_tour_with_a_reason():
    now = {"t": 0.0}
    service = FakeService(alive=False)
    health, ladder = _health(service, now)
    ladder.observed()

    health.check()               # first death: restart
    service._alive = False       # it died again
    reason = health.check()

    assert reason is not None
    assert "perception" in reason.lower()
    assert service.restarts == 1, "it must not keep restarting forever"


def test_a_stalled_but_living_worker_is_also_treated_as_dead():
    """Alive but never progressing is the other death mode."""
    now = {"t": 0.0}
    service = FakeService(alive=True)
    health, ladder = _health(service, now, dead_after_s=15.0)
    ladder.observed()

    now["t"] = 20.0
    assert health.check() is None
    assert service.restarts == 1, "a stalled worker was not restarted"


def test_the_heartbeat_is_logged_when_the_policy_fires():
    """Diagnostic only — it must never decide anything."""
    now = {"t": 0.0}
    service = FakeService(alive=False)
    health, ladder = _health(service, now)
    ladder.observed()
    health.check()

    assert any("heartbeat" in message.lower() for message in logs), (
        "the heartbeat was not recorded when the restart policy fired"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_worker_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostcursor.perception.health'`

- [ ] **Step 3: Write minimal implementation**

```python
# ghostcursor/perception/health.py
"""Detecting a perception worker that has stopped doing its job.

Two signals drive recovery, and a third is diagnosis only:

  * the staleness clock detects "alive but not progressing" — it is already
    needed to decide what the overlay shows, so it is free here;
  * Thread.is_alive() distinguishes "the worker raised and exited", which the
    clock alone would report as merely stale forever;
  * the heartbeat counter is LOGGED when the policy fires and never read by
    it. It separates "blocked in a slow UIA call" from "alive but looping
    through silent failures" after the fact, without that distinction
    quietly influencing behaviour.

Policy: restart exactly once, then end the tour with an explicit reason. A
worker that dies twice is not going to recover, and sitting silently stuck is
the failure mode this exists to prevent.
"""

from __future__ import annotations

from typing import Callable

#: How long without a confirmed-fresh observation before a living worker is
#: treated as dead. Comfortably past the ~10s bound a hung application
#: imposes, so an ordinary hang is not mistaken for a dead worker.
DEFAULT_DEAD_AFTER_S = 15.0


class WorkerHealth:
    def __init__(
        self,
        service,
        ladder,
        dead_after_s: float = DEFAULT_DEAD_AFTER_S,
        log: Callable[[str], None] = print,
    ) -> None:
        self.service = service
        self.ladder = ladder
        self.dead_after_s = dead_after_s
        self.log = log
        self._restarted = False

    def check(self) -> str | None:
        """Called once per tick. Returns a failure reason when the tour
        should end, otherwise None."""
        dead = not self.service.is_alive()
        stalled = self.ladder.age() > self.dead_after_s
        if not (dead or stalled):
            return None

        cause = "exited" if dead else f"stalled for {self.ladder.age():.1f}s"
        # Heartbeat is recorded, never consulted: it tells a later reader
        # whether the worker was blocked in a call or looping through
        # failures.
        self.log(
            f"Ghost Cursor: perception worker {cause} "
            f"(heartbeat {self.service.heartbeat})"
        )

        if self._restarted:
            return f"perception stopped working ({cause}); ending the tour"

        self._restarted = True
        self.service.restart()
        self.log("Ghost Cursor: restarted the perception worker")
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -B -m pytest tests/test_worker_health.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/perception/health.py tests/test_worker_health.py
git commit -m "feat: detect and recover a dead perception worker"
```

---

### Task 7: Wire it into the live run

**Files:**
- Modify: `ghostcursor/run.py`
- Test: `tests/test_run_threaded.py`

**Interfaces:**
- Consumes: everything above
- Produces: `run_tour` drives the tour from `PerceptionService`, applies the staleness ladder to rendering, and ends the tour on `WorkerHealth.check()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_threaded.py
"""ESC stays responsive while the target application is hung.

This is the property the whole change exists for, and it could not be tested
before: with perception on the UI thread, a hung target blocked the tick for
tens of seconds and no amount of polling helped.
"""

import time

from ghostcursor.perception.service import PerceptionService
from ghostcursor.perception.uia import iter_elements
from tests.test_hung_window import HungWindow


def test_reading_the_slot_stays_fast_while_the_target_is_hung():
    with HungWindow() as hung:
        service = PerceptionService(hung.title_re, walker=iter_elements, interval_s=0.05)
        service.start()
        try:
            time.sleep(0.5)  # the worker is now blocked inside UIA
            start = time.perf_counter()
            for _ in range(100):
                service.latest()
            elapsed = time.perf_counter() - start
        finally:
            service.stop()

    assert elapsed < 0.5, (
        f"100 slot reads took {elapsed:.2f}s against a hung target — the UI "
        "thread is still coupled to perception"
    )


def test_a_hung_target_never_produces_an_observation_but_does_not_crash():
    with HungWindow() as hung:
        service = PerceptionService(hung.title_re, walker=iter_elements, interval_s=0.05)
        service.start()
        try:
            time.sleep(1.0)
            observation = service.latest()
            alive = service.is_alive()
        finally:
            service.stop()

    assert observation is None, "a hung window somehow produced an observation"
    assert alive, "the worker died instead of blocking"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -B -m pytest tests/test_run_threaded.py -v`
Expected: FAIL — `tests/test_hung_window.py` exists from Task 1, so this should actually pass once Tasks 1 and 5 are done. If it fails, read the error: a failure here means the service is not decoupled.

- [ ] **Step 3: Wire the service into `run_tour`**

In `ghostcursor/run.py`, inside `run_tour`, replace the direct perception calls. After the app-info/store setup and BEFORE `window.create_overlay_window()`, start the service; drive the tour from it; and stop it in the same `finally` that closes the store:

```python
    from ghostcursor.perception.health import WorkerHealth
    from ghostcursor.perception.service import PerceptionService
    from ghostcursor.reasoning.staleness import Freshness, StalenessLadder

    service = PerceptionService(title_re)
    ladder = StalenessLadder()
    health = WorkerHealth(service=service, ladder=ladder)
    service.start()
```

The collaborators read the slot instead of walking:

```python
    def snapshotter():
        observation = service.latest()
        if observation is None:
            return Snapshot(title="", elements=())
        ladder.observed()
        return observation.snapshot

    def grounder_from_slot(step, i, elements=None):
        observation = service.latest()
        if observation is None:
            return None
        return live_grounder(step, i, observation.elements)
```

where `live_grounder` is the existing `make_grounder(...)` result. In the tick loop, apply the ladder to what is drawn and let health end the tour:

```python
            reason = health.check()
            if reason is not None:
                print(f"Stopped: {reason}")
                break

            state = tour.tick()
            freshness = ladder.freshness()
            if freshness is Freshness.HIDDEN:
                window.clear_hint(hwnd)
            elif tour._grounded is not None:
                left, top, right, bottom = tour._grounded.bbox
                window.set_hint(
                    hwnd, (left + right) // 2, (top + bottom) // 2,
                    freshness=freshness,
                )
```

And in the `finally`, before closing the store:

```python
        service.stop()
```

- [ ] **Step 4: Run the suite**

Run: `python -B -m pytest tests/ -q`
Expected: all pass, including the 134 pre-existing tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/run.py tests/test_run_threaded.py
git commit -m "feat: drive the tour from the perception worker"
```

---

### Task 8: Documentation

**Files:**
- Modify: `FLOW.md`, `DECISIONS.md`, `CLAUDE.md`

- [ ] **Step 1: Update FLOW.md**

Replace the guided-tour call graph with the threaded one: the UI thread polling ESC/SPACE, reading `service.latest()`, ticking, applying the ladder and pumping messages; the worker looping, walking, publishing into the slot and incrementing the heartbeat. Add `perception/service.py`, `perception/health.py` and `reasoning/staleness.py` to the Files table with accurate one-line roles. Update the verification numbers to the real ones from the final run.

- [ ] **Step 2: Add DECISIONS.md entries**

The file currently ends at D020. Add, matching the existing entries' format and depth:

- **D021 — perception runs on a worker thread.** The measurement that forced it (a non-pumping window blocks a UIA walk for 40s first contact, ~10s after, 80x the tick ceiling, no timeout to tune), why the ceiling test could not catch it (it uses an absent window, not a hung one), and why a watchdog cannot substitute (`DestroyWindow` from a non-owning thread returns `Access is denied`; `PostMessage` needs the pump a blocked tick is not running).
- **D022 — a single timestamped slot, not a queue or futures.** A depth-1 always-overwrite queue is the slot with extra ceremony; a timestamp captures the one thing futures offered here without forcing async control flow into `GuidedTour` or changing a single fake.
- **D023 — the staleness ladder, and why untimestamped means fresh.** The staged thresholds, the debounced recovery, and that `observed_at == 0.0` is treated as fresh so synchronous and faked perception keep working.

- [ ] **Step 3: Update CLAUDE.md**

Add the threading rule to the tech-stack section: perception runs on a worker thread that owns its COM apartment; the UI thread never blocks on it; only frozen dataclasses cross the boundary. Refresh any test counts that are now stale by checking them rather than assuming.

- [ ] **Step 4: Verify and commit**

```bash
python -B -m pytest tests/ -q
git add FLOW.md DECISIONS.md CLAUDE.md
git commit -m "docs: record the threading decisions"
```

---

## Self-Review

**Spec coverage.** §3 architecture → Task 5 (slot, timestamp, throttle). §4 contract preserved → Task 5 plus Task 7's adapters; asserted by the whole suite passing unchanged. §5 staleness ladder → Task 3, rendered by Task 4, applied by Task 7. §6 the freshness gate → Task 2. §7 worker lifecycle, restart-once, diagnostic heartbeat → Task 6. §8 COM ownership → Task 5's `_run`. §9 error handling: absent target (unchanged), hung target → Tasks 1 and 7, closes-mid-walk (existing test), worker raises → Tasks 5 and 6, no observation yet → Task 5's `latest() is None` and Task 7's empty-snapshot fallback. §10 testing → the hung-window harness in Task 1 underpins Tasks 5–7.

**Not covered, deliberately:** §12's two open questions. The staleness thresholds and the throttle interval are judgement, exposed as constructor parameters so they can be tuned against a real hanging app without a code change.

**Placeholder scan.** No TBD/TODO markers. Task 8 is prose because it is documentation, and each bullet names the specific content required.

**Type consistency.** `Snapshot(title, elements, focused_automation_id="", observed_at=0.0)` is used identically in Tasks 2, 5 and 7. `Observation(snapshot, elements, observed_at, ok)` matches between Task 5's definition and Task 7's readers. `Freshness.FRESH/DIMMED/HIDDEN` is consistent across Tasks 3, 4 and 7. `StalenessLadder.observed()/freshness()/age()` matches between Tasks 3, 6 and 7. `WorkerHealth.check() -> str | None` matches Task 6's definition and Task 7's use. `service.latest()/is_alive()/restart()/heartbeat` are the same names in Tasks 5, 6 and 7.

**One risk worth naming.** Task 4 changes the ring colour path, and the two pixel harnesses assert on ring colour. They are the one place this plan can break something outside pytest, which is why that task's final step calls them out explicitly.

**Per D018**, the safety-critical properties are mutation-verified rather than assumed: breaking the newer-than-`_before` gate (Task 2), the `is_alive` check or the restart-once policy (Task 6), and the slot's non-blocking read (Task 5) must each fail a test.
