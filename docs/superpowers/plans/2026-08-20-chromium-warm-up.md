# Chromium Warm-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a cold, UIA-capable application being escalated to OCR while its accessibility tree is still being built, by giving each newly-seen target window a short grace period before tier 2 may be requested.

**Architecture:** Do not detect readiness — the system already has a perfect readiness signal, which is *grounding succeeded*. What is missing is patience. A `WarmUp` object, keyed by **window handle**, suppresses `service.request_tier2()` for `WARMUP_BUDGET_S` after a handle is first seen, and closes permanently for that handle the first time grounding succeeds. Nothing compares two observations, so the non-monotonic element count is irrelevant by construction. The handle must therefore cross the worker boundary, which it currently does not.

**Tech Stack:** Python 3.12, pywin32, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-19-chromium-warm-up-design.md`
**Measurements:** `docs/superpowers/specs/2026-08-19-cold-electron-probe-findings.md`

## Global Constraints

- `DEFAULT_WARMUP_BUDGET_S = 2.0`. Swept on VS Code (grounded 0.57 s / 0.39 s after the window) and Discord (0.92 s after the real window). It is a constructor parameter, never a hardcoded literal at a call site.
- **Only primitives cross the thread boundary** (D021). The handle is published as an `int` on `Observation`. No COM object, no HWND wrapper, ever.
- **One shared clock** (D026). `run_tour` already documents that its `clock` is a single time source; `WarmUp` is constructed with that same `clock`, never with `time.monotonic` directly.
- **Ordered-sequence tests on an injected clock** (D026). Never assert end state for time-dependent behaviour.
- **Mutation-verify** (D018). Every safety-relevant test must be shown to fail when the behaviour it protects is deliberately broken.
- **State the property and the invariant, and whether the invariant implies it** (D031).
- **Nothing self-reviewed is ground truth** (D032). Each task is reviewed by something other than its author.
- **Commit as soon as your tests pass**, before any mutation or verification work. Five agents were lost to capacity limits mid-milestone; every one that had committed early kept its work.
- Windows-only. Never move the real cursor or synthesise input (D006).

## File Structure

| File | Responsibility |
|---|---|
| `ghostcursor/perception/warmup.py` *(new)* | `WarmUp` — pure policy over `(hwnd, clock)`. No Win32, no COM, no I/O. Sits in `perception/` because it answers "is perception ready for this window", but note it runs on the **UI thread**, unlike `perception/tier2.py` which is worker-side. |
| `tests/test_warmup.py` *(new)* | Unit sequence tests for `WarmUp`, including the Discord splash case. |
| `ghostcursor/perception/service.py` | Add `Observation.target_hwnd: int` and an injectable `hwnd_source`, so the handle reaches the UI thread. |
| `tests/test_perception_service.py` | Extend: the worker publishes the handle; a failing `hwnd_source` publishes 0 rather than killing the walk. |
| `ghostcursor/run.py` | Gate `service.request_tier2(i)` on `warmup.allows_tier2(...)`; call `warmup.note_grounded(...)` when grounding succeeds. |
| `tests/test_warmup_tour.py` *(new)* | Timeline tests through `run_tour`, mirroring `tests/test_freshness_timeline.py`. |

---

### Task 1: `WarmUp` policy object

**Files:**
- Create: `ghostcursor/perception/warmup.py`
- Test: `tests/test_warmup.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `DEFAULT_WARMUP_BUDGET_S: float`; `class WarmUp` with `__init__(self, budget_s: float = DEFAULT_WARMUP_BUDGET_S, clock: Callable[[], float] = time.monotonic)`, `allows_tier2(self, hwnd: int) -> bool`, `note_grounded(self, hwnd: int) -> None`.

**Property this protects:** a cold but UIA-capable window is not escalated to OCR before its tree is ready.
**Invariant enforced:** `request_tier2` is never called while that window's warm-up is open.
**Does the invariant imply the property?** Only if warm-up is open on *the window the step is being grounded against*. Keyed by title, it is not — Discord's `Discord Updater` splash would absorb the budget. That is why the key is the HWND, and why the splash test below is not optional decoration.

- [ ] **Step 1: Write the failing tests**

```python
"""WarmUp: tier 2 is suppressed briefly after a window handle is first seen."""

from ghostcursor.perception.warmup import DEFAULT_WARMUP_BUDGET_S, WarmUp


class FakeClock:
    """One hand-advanced time source. Warm-up is time-dependent, so every
    test here asserts an ORDERED SEQUENCE of answers rather than an end
    state (D026): 'it eventually allows tier 2' is true of a no-op."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_first_sight_of_a_handle_suppresses_tier2():
    warm = WarmUp(budget_s=2.0, clock=FakeClock())
    assert warm.allows_tier2(1001) is False


def test_suppressed_for_the_whole_budget_then_allowed():
    clock = FakeClock()
    warm = WarmUp(budget_s=2.0, clock=clock)

    seen = [warm.allows_tier2(1001)]      # t=0.0, opens here
    clock.advance(0.5)
    seen.append(warm.allows_tier2(1001))  # t=0.5
    clock.advance(1.4)
    seen.append(warm.allows_tier2(1001))  # t=1.9, still inside
    clock.advance(0.2)
    seen.append(warm.allows_tier2(1001))  # t=2.1, expired
    clock.advance(10.0)
    seen.append(warm.allows_tier2(1001))  # t=12.1, stays expired

    assert seen == [False, False, False, True, True]


def test_grounding_closes_warm_up_permanently():
    clock = FakeClock()
    warm = WarmUp(budget_s=2.0, clock=clock)

    assert warm.allows_tier2(1001) is False
    warm.note_grounded(1001)
    seen = [warm.allows_tier2(1001)]
    clock.advance(0.1)
    seen.append(warm.allows_tier2(1001))
    assert seen == [True, True], "a proven tree never needs the allowance again"


def test_a_splash_window_does_not_consume_the_real_windows_budget():
    """The measured Discord case. 'Discord Updater' is a separate HWND that
    matches the same title and lives ~5s; keyed by title, it would expire the
    budget before the real window exists and escalate to OCR on an app whose
    tree is ready in 0.92s."""
    clock = FakeClock()
    warm = WarmUp(budget_s=2.0, clock=clock)
    splash, real = 329088, 1638728

    warm.allows_tier2(splash)             # t=0.0, splash opens
    clock.advance(5.0)
    assert warm.allows_tier2(splash) is True, "splash's own budget expired"

    seen = [warm.allows_tier2(real)]      # t=5.0, real window: fresh budget
    clock.advance(1.0)
    seen.append(warm.allows_tier2(real))  # t=6.0, still inside its own budget
    clock.advance(1.5)
    seen.append(warm.allows_tier2(real))  # t=7.5, expired

    assert seen == [False, False, True]


def test_handles_are_independent():
    warm = WarmUp(budget_s=2.0, clock=FakeClock())
    warm.allows_tier2(1001)
    warm.note_grounded(1001)
    assert warm.allows_tier2(1001) is True
    assert warm.allows_tier2(2002) is False, "closing one window closed another"


def test_absent_window_does_not_suppress():
    """hwnd 0 means no matching window was observed. There is nothing to be
    patient ABOUT, and suppressing here would silently disable tier 2 whenever
    the walk transiently found no window."""
    warm = WarmUp(budget_s=2.0, clock=FakeClock())
    assert warm.allows_tier2(0) is True


def test_default_budget_is_two_seconds():
    assert DEFAULT_WARMUP_BUDGET_S == 2.0


def test_opens_counts_distinct_handles_only():
    """Diagnostic only -- nothing reads it to decide. It exists so that the
    one unmeasured risk in this design (an app recreating its window faster
    than the budget, suppressing tier 2 forever) is visible as a number rather
    than rediscovered by wondering why OCR never fires."""
    warm = WarmUp(budget_s=2.0, clock=FakeClock())
    assert warm.opens == 0
    warm.allows_tier2(1001)
    warm.allows_tier2(1001)
    assert warm.opens == 1, "re-checking one handle is not a new window"
    warm.allows_tier2(2002)
    assert warm.opens == 2
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_warmup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostcursor.perception.warmup'`

- [ ] **Step 3: Write the implementation**

```python
"""Patience before escalating to tier 2, keyed by window handle.

A cold Chromium application populates its accessibility tree over a second or
so. `run.py` requests tier 2 the moment grounding fails, so a cold start
escalates straight to OCR: wasted reads, and -- worse -- a chance of drawing an
amber INFERRED ring off a pixel match when a cyan ring off a confirmed control
was half a second away. The ring colour is how the user calibrates trust (D006).

This does NOT try to detect readiness. Every attempt to do so was ruled out by
measurement: 'furniture but no content' is transient in VS Code and TERMINAL in
Acrobat, and the element count is non-monotonic even in steady state, so
comparing consecutive observations is unsound. The system already has a perfect
readiness signal -- grounding succeeded -- and what was missing was patience.

Keyed by HWND, not by the title regex. Discord's cold start puts up a window
titled 'Discord Updater' which fully matches windows_matching('.*Discord.*') and
lives about five seconds before the real window exists, as a separate handle. A
title-keyed warm-up spends its whole budget there and leaves the real window
with none.

Runs on the UI THREAD -- unlike perception/tier2.py, which is worker-side.
"""

import time
from typing import Callable

#: Swept, not guessed. VS Code grounded its targets 0.57s and 0.39s after the
#: window appeared; Discord grounded all six 0.92s after its real window. No
#: element was ever observed to ground slowly-but-eventually, so a larger budget
#: buys nothing -- it cannot rescue an element that is simply absent. Every
#: second here is a second a genuinely UIA-blind app (Acrobat) waits before OCR
#: engages, on every cold start, forever.
DEFAULT_WARMUP_BUDGET_S = 2.0


class WarmUp:
    """Per-window-handle grace period before tier 2 may be requested."""

    def __init__(
        self,
        budget_s: float = DEFAULT_WARMUP_BUDGET_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._budget_s = budget_s
        self._clock = clock
        #: hwnd -> the time its warm-up opened.
        self._opened: dict[int, float] = {}
        #: Handles that have grounded at least once. Their tree is proven, so
        #: they never need the allowance again -- a later step that fails to
        #: ground escalates immediately, as it does today.
        self._closed: set[int] = set()
        #: How many distinct handles have opened a warm-up. DIAGNOSTIC ONLY --
        #: never read by policy, exactly like the worker heartbeat under D024.
        #: The one unmeasured risk in this design is an application that
        #: destroys and recreates its top-level window faster than the budget,
        #: which would re-open warm-up forever and suppress tier 2 for good. It
        #: is invisible from the outside -- tier 2 simply never fires -- so this
        #: counter is what makes it legible. Every measured run saw 2 (Discord:
        #: its updater, then the app); dozens means window churn, and that is
        #: the FIRST thing to check if tier 2 ever seems not to fire.
        self.opens = 0

    def allows_tier2(self, hwnd: int) -> bool:
        """True when tier 2 may be requested for `hwnd` right now.

        Opens the warm-up as a side effect the first time a handle is seen,
        which is the only moment 'first observation of this window' is
        observable from here.
        """
        if hwnd <= 0:
            return True
        if hwnd in self._closed:
            return True
        opened = self._opened.get(hwnd)
        if opened is None:
            self._opened[hwnd] = self._clock()
            self.opens += 1
            return False
        return (self._clock() - opened) >= self._budget_s

    def note_grounded(self, hwnd: int) -> None:
        """Close `hwnd`'s warm-up permanently: its tree is demonstrably usable."""
        if hwnd > 0:
            self._closed.add(hwnd)
            self._opened.pop(hwnd, None)
```

`opens` is deliberately a plain public attribute, not a property: it is read by humans and by the diagnostic test, never by policy.

**Two accepted limitations, stated rather than discovered later.** `_opened` and `_closed` grow with the number of distinct matching top-level windows seen during one run — two, in every Discord run measured — and are not evicted. And Windows recycles handle values, so a recycled handle could inherit a closed warm-up; that degrades to today's behaviour (tier 2 allowed immediately), not to a new failure.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `python -m pytest tests/test_warmup.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit — do this now, before the mutation work below**

```bash
git add ghostcursor/perception/warmup.py tests/test_warmup.py
git commit -m "feat: WarmUp, per-HWND patience before escalating to tier 2"
git push origin main
```

- [ ] **Step 6: Mutation-verify (D018), one mutation at a time, reverting between**

Apply each mutation, run `python -m pytest tests/test_warmup.py -v`, record which test caught it, then `git checkout -- ghostcursor/perception/warmup.py`.

| # | Mutation | Must fail |
|---|---|---|
| 1 | `allows_tier2` returns `True` unconditionally (first line) | `test_first_sight_of_a_handle_suppresses_tier2` |
| 2 | `allows_tier2` returns `False` once opened, never expiring | `test_suppressed_for_the_whole_budget_then_allowed` |
| 3 | `note_grounded` becomes a no-op (`pass`) | `test_grounding_closes_warm_up_permanently` |
| 4 | Key by a constant instead of the handle — use key `1` throughout (`self._opened.get(1)`, `self._opened[1] = ...`, `self._closed.add(1)`), since the `hwnd <= 0` guard returns early and `0` would not exercise it | `test_a_splash_window_does_not_consume_the_real_windows_budget` **and** `test_handles_are_independent` |

Mutation 4 is the one that matters: it is exactly "keyed by title, not by handle", the measured Discord defect. If it does not fail a test, the plan's central claim is untested.

- [ ] **Step 7: Record the mutation results and commit**

Create `docs/superpowers/ledgers/2026-08-20-chromium-warm-up-ledger.md` and record the four results, naming which test caught each. Per D034 a claim like "mutation-verified" must name where it is recorded.

```bash
git add docs/superpowers/ledgers/2026-08-20-chromium-warm-up-ledger.md
git commit -m "docs: record WarmUp mutation results"
git push origin main
```

---

### Task 2: Publish the target window handle across the thread boundary

**Files:**
- Modify: `ghostcursor/perception/service.py` — `Observation` (~line 73), `PerceptionService.__init__` (~line 103), `_run` (~lines 329–380)
- Modify: `ghostcursor/perception/uia.py` — add `first_matching_hwnd` beneath `windows_matching`
- Test: `tests/test_perception_service.py` (extend)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `Observation.target_hwnd: int` (0 when no matching window was observed); `PerceptionService(..., hwnd_source: Callable[[str], int] = first_matching_hwnd)`; `ghostcursor.perception.uia.first_matching_hwnd(title_re: str) -> int`.

**Why this task exists:** `Snapshot` carries `title`, not a handle, so today the UI thread cannot name the window it is grounding against. Task 3 cannot be written without it. `hwnd_source` is injectable for the same reason `walker` and `clock` already are — tests must not need a real window.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_perception_service.py`:

```python
def test_worker_publishes_the_target_window_handle():
    """The handle must cross the boundary as a plain int (D021): warm-up is
    keyed on it, and a title cannot distinguish Discord's updater splash from
    Discord itself."""
    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        interval_s=0.01,
    )
    service.start()
    try:
        observation = _wait_for_observation(service)
    finally:
        service.stop()
    assert observation.target_hwnd == 4242


def test_absent_window_publishes_handle_zero():
    service = PerceptionService(
        title_re=".*Nothing.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 0,
        interval_s=0.01,
    )
    service.start()
    try:
        observation = _wait_for_observation(service)
    finally:
        service.stop()
    assert observation.target_hwnd == 0


def test_a_failing_hwnd_source_does_not_kill_the_walk():
    """The handle is a nicety; the walk is the product. A hwnd_source that
    raises must degrade to 0, not suppress the observation -- otherwise a
    transient enumeration failure blinds perception entirely."""

    def boom(_):
        raise OSError("enumeration failed")

    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=boom,
        interval_s=0.01,
    )
    service.start()
    try:
        observation = _wait_for_observation(service)
    finally:
        service.stop()
    assert observation.ok is True
    assert observation.target_hwnd == 0
```

If `_wait_for_observation` does not already exist in that file, add it:

```python
def _wait_for_observation(service, timeout_s: float = 5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        observation = service.latest()
        if observation is not None:
            return observation
        time.sleep(0.01)
    raise AssertionError("no observation published within the timeout")
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_perception_service.py -v -k "hwnd or handle"`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'hwnd_source'`

- [ ] **Step 3: Add `first_matching_hwnd` to `ghostcursor/perception/uia.py`**

Place it directly beneath `windows_matching`, which it wraps:

```python
def first_matching_hwnd(title_re: str) -> int:
    """The topmost visible, non-minimized, on-screen window matching title_re,
    or 0 when there is none.

    Warm-up is keyed on this, so it MUST agree with the window grounding walks
    -- both go through windows_matching for that reason (see its docstring on
    identity and grounding agreeing on which window they mean).
    """
    matches = windows_matching(title_re)
    return matches[0] if matches else 0
```

- [ ] **Step 4: Add the field and the injection point in `service.py`**

Import it: `from ghostcursor.perception.uia import Element, first_matching_hwnd, iter_elements`

Add to `Observation`, after `tier2_max_runs`:

```python
    #: The target window this observation was walked against, or 0 if none was
    #: found. A plain int by design -- only primitives cross the worker
    #: boundary (D021). Warm-up is keyed on it because a title regex cannot
    #: distinguish Discord's 'Discord Updater' splash from Discord itself, and
    #: those are different HWNDs.
    target_hwnd: int = 0
```

Add the constructor parameter beside `walker`:

```python
        hwnd_source: Callable[[str], int] = first_matching_hwnd,
```

and store it: `self.hwnd_source = hwnd_source`

In `_run`, inside the existing `try:` that wraps the walk, immediately after `elements = tuple(self.walker(self.title_re))`:

```python
                    target_hwnd = self._safe_hwnd()
```

Extend the `walked` tuple to carry it:

```python
                    walked = (
                        take_snapshot(
                            self.title_re, elements=elements, observed_at=observed_at
                        ),
                        elements,
                        observed_at,
                        target_hwnd,
                    )
```

Unpack it: `snapshot, elements, observed_at, target_hwnd = walked`

And pass it: `target_hwnd=target_hwnd,` in the `Observation(...)` call.

Add the helper as a method on `PerceptionService`:

```python
    def _safe_hwnd(self) -> int:
        """The handle is a nicety; the walk is the product. A failure here
        degrades to 0 rather than discarding an observation that is otherwise
        perfectly good."""
        try:
            return int(self.hwnd_source(self.title_re))
        except Exception:
            return 0
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `python -m pytest tests/test_perception_service.py -v`
Expected: all pass, including the three new ones.

- [ ] **Step 6: Run the fast suite for regressions**

Run:
```bash
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
```
Expected: 280 existing + 3 new = 283 passed. **Never run this beside another pytest session** (D025).

- [ ] **Step 7: Commit**

```bash
git add ghostcursor/perception/service.py ghostcursor/perception/uia.py tests/test_perception_service.py
git commit -m "feat: publish the target window handle on Observation"
git push origin main
```

---

### Task 3: Gate the tier-2 request on warm-up

**Files:**
- Modify: `ghostcursor/run.py` — `run_tour` signature (~line 243), the grounding closure (~lines 398–437)
- Test: `tests/test_warmup_tour.py` *(new)*

**Interfaces:**
- Consumes: `WarmUp`, `DEFAULT_WARMUP_BUDGET_S` (Task 1); `Observation.target_hwnd` (Task 2).
- Produces: `run_tour(..., warmup_budget_s: float = DEFAULT_WARMUP_BUDGET_S)`.

**Property this protects:** a cold, UIA-capable application is not shown an amber OCR ring when a cyan confirmed-control ring is under a second away.
**Invariant enforced:** `service.request_tier2(i)` is not called while the current target window's warm-up is open.
**Does the invariant imply the property?** Yes for the cold-start case, given Task 1's HWND keying — with one honest gap, stated so it is not discovered later as a surprise: warm-up delays the *request*, so a UIA-blind application (Acrobat) waits the full budget before OCR engages on every cold start. That is the measured, accepted cost, and it is why the budget is 2.0 s and not the 5.0 s originally drafted.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_warmup_tour.py`:

```python
"""Warm-up, driven through run_tour on an injected clock.

Mirrors tests/test_freshness_timeline.py -- read that first for the harness
shape. These assert an ORDERED SEQUENCE of tier-2 requests, not an end state
(D026): 'tier 2 is eventually requested' is true even with warm-up disabled.
"""

import inspect

import ghostcursor.run as run_module
from ghostcursor.perception.warmup import DEFAULT_WARMUP_BUDGET_S


def test_default_budget_flows_through_to_run_tour():
    default = inspect.signature(run_module.run_tour).parameters[
        "warmup_budget_s"
    ].default
    assert default == DEFAULT_WARMUP_BUDGET_S


def test_a_cold_window_that_grounds_inside_the_budget_never_asks_for_tier2(
    warmup_harness,
):
    """The whole point. VS Code grounded 0.57s after its window appeared and
    Discord 0.92s; both are inside a 2.0s budget, so neither should ever have
    reached OCR."""
    h = warmup_harness(budget_s=2.0, hwnd=1638728)

    h.tick()                 # t=0.0  grounding fails, warm-up opens
    h.advance(0.5)
    h.tick()                 # t=0.5  still failing, still inside the budget
    h.ground_from_now_on()
    h.advance(0.4)
    h.tick()                 # t=0.9  UIA answers, as measured

    assert h.tier2_requests == [], "escalated to OCR while UIA was still coming"


def test_a_window_that_never_grounds_asks_once_the_budget_expires(warmup_harness):
    h = warmup_harness(budget_s=2.0, hwnd=1638728)

    h.tick()                 # t=0.0
    h.advance(1.9)
    h.tick()                 # t=1.9  inside
    inside = list(h.tier2_requests)
    h.advance(0.2)
    h.tick()                 # t=2.1  expired
    after = list(h.tier2_requests)

    assert inside == [], "asked before the budget expired"
    assert after, "never asked after the budget expired -- tier 2 is dead"


def test_warm_up_does_not_reopen_after_a_successful_grounding(warmup_harness):
    """Closes permanently on first success: a LATER step that fails to ground
    must escalate immediately, with no second allowance."""
    h = warmup_harness(budget_s=2.0, hwnd=1638728)

    h.tick()
    h.ground_from_now_on()
    h.advance(0.3)
    h.tick()                 # grounds -> warm-up closes
    h.stop_grounding()
    h.advance(0.1)
    h.tick()                 # fails again, 0.1s later

    assert h.tier2_requests, "a second allowance was granted after the tree was proven"


def test_a_splash_window_does_not_spend_the_real_windows_budget(warmup_harness):
    """The measured Discord case, end to end: 'Discord Updater' (hwnd 329088)
    for ~5s, then the real window (hwnd 1638728) whose tree is ready in 0.92s."""
    h = warmup_harness(budget_s=2.0, hwnd=329088)

    h.tick()                 # t=0.0  splash seen
    h.advance(5.0)
    h.tick()                 # t=5.0  splash budget long expired
    h.set_hwnd(1638728)      # the real window replaces it
    h.tier2_requests.clear()
    h.tick()                 # t=5.0  real window, first sight
    h.advance(0.9)
    h.ground_from_now_on()
    h.tick()                 # t=5.9  grounds, as measured

    assert h.tier2_requests == [], (
        "the splash's expired budget was reused for the real window"
    )
```

Add the harness as a fixture in the same file. Build it on whatever `run_tour` driver `tests/test_freshness_timeline.py` already uses — **read that file and reuse its fixtures rather than inventing a second driver.** The harness must expose exactly: `tick()`, `advance(dt)`, `set_hwnd(h)`, `ground_from_now_on()`, `stop_grounding()`, and a `tier2_requests` list recording each `request_tier2` call, with `service.latest()` returning an `Observation` whose `target_hwnd` is the harness's current handle.

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_warmup_tour.py -v`
Expected: FAIL — `KeyError: 'warmup_budget_s'` on the signature test, and the rest failing because tier 2 is requested immediately.

- [ ] **Step 3: Wire warm-up into `run.py`**

Import at the top:

```python
from ghostcursor.perception.warmup import DEFAULT_WARMUP_BUDGET_S, WarmUp
```

Add to the `run_tour` signature, after `sleeper`:

```python
    warmup_budget_s: float = DEFAULT_WARMUP_BUDGET_S,
```

Construct it near the other per-run state, **with `run_tour`'s own `clock`** — the docstring's insistence on one shared time source applies here too:

```python
    #: Patience before escalating to tier 2 on a freshly-seen window. Same
    #: clock as the deadline, the health budget and the staleness ladder; two
    #: independently-driftable clocks here is the D026 failure exactly.
    warmup = WarmUp(budget_s=warmup_budget_s, clock=clock)
```

Replace the unconditional `service.request_tier2(i)` at ~line 419 with:

```python
                # Warm-up. A cold Chromium tree is populating, not blind: VS
                # Code grounded its targets 0.57s after the window appeared and
                # Discord 0.92s. Escalating inside that window burns OCR reads
                # and risks drawing an amber INFERRED ring when a cyan one off a
                # confirmed control was half a second away. Keyed by HANDLE, not
                # title -- Discord's 'Discord Updater' splash matches the same
                # regex and is a different window.
                target_hwnd = observation.target_hwnd if observation is not None else 0
                if not warmup.allows_tier2(target_hwnd):
                    return None
                service.request_tier2(i)
```

And close warm-up where grounding succeeds. In the same closure, at the early success path (the `if target is not None:` that calls `service.cancel_tier2(i)`), add before its `return`:

```python
                    warmup.note_grounded(
                        observation.target_hwnd if observation is not None else 0
                    )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `python -m pytest tests/test_warmup_tour.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the fast suite**

Run:
```bash
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
```
Expected: all pass. `test_tier2_timeline.py`, `test_first_paint.py` and `test_freshness_timeline.py` are the likely breakages — they may assume tier 2 is requested on the first failing tick. If one fails, **do not delete the assertion**: give that test's fake observation a `target_hwnd` and either advance past the budget or pass `warmup_budget_s=0.0`, and add a one-line comment saying which it chose and why.

- [ ] **Step 6: Commit**

```bash
git add ghostcursor/run.py tests/test_warmup_tour.py
git commit -m "feat: hold tier 2 back during a new window's warm-up"
git push origin main
```

- [ ] **Step 7: Mutation-verify (D018)**

| # | Mutation in `run.py` | Must fail |
|---|---|---|
| 1 | Delete the `if not warmup.allows_tier2(...): return None` guard | `test_a_cold_window_that_grounds_inside_the_budget_never_asks_for_tier2` |
| 2 | Make the guard permanent — `return None` unconditionally in its place | `test_a_window_that_never_grounds_asks_once_the_budget_expires` |
| 3 | Delete the `warmup.note_grounded(...)` call | `test_warm_up_does_not_reopen_after_a_successful_grounding` |
| 4 | Pass a constant instead of the handle: `warmup.allows_tier2(1)` | `test_a_splash_window_does_not_spend_the_real_windows_budget` |

Append the results to the ledger from Task 1 Step 7, then commit.

- [ ] **Step 8: Run the hung-target tests, ALONE**

Run:
```bash
python -m pytest tests/test_hung_window.py tests/test_perception_service_hung.py tests/test_run_threaded.py -q
```
Expected: 13 passed, ~128 s. **Nothing else may run concurrently** — a hung window taxes UIA desktop-wide, measured 6.28 s versus 100.13 s (D025).

- [ ] **Step 9: Pixel harnesses**

```bash
python -m tests.test_overlay
python -m tests.test_end_to_end
```
Expected: 16 and 8 checks pass.

---

### Task 4: Documentation

**Files:**
- Modify: `DECISIONS.md`, `FLOW.md`, `CLAUDE.md`

**Interfaces:** consumes the finished behaviour of Tasks 1–3.

- [ ] **Step 1: Add the decision entry**

Append to `DECISIONS.md` as the next free number (D035 at time of writing — **check, do not assume**). It must state: the trigger (`run.py` escalating on the first failing tick of a cold start); that readiness detection was ruled out by measurement, not preference; the budget with its measured basis (VS Code 0.57 s / 0.39 s, Discord 0.92 s) citing `docs/superpowers/specs/2026-08-19-cold-electron-probe-findings.md` per D034; that it is keyed by HWND, with the Discord updater as the reason; and the accepted cost — a UIA-blind app waits the budget on every cold start, and an app that recreates its window faster than the budget could suppress tier 2 indefinitely.

  **Two things must land in `DECISIONS.md` itself, not only in the spec.** This project has already lost hard-won findings to disposable workspaces (D033), and a spec can be archived while `DECISIONS.md` is the file the next person reads first.

  1. **The window-churn risk, written as a diagnostic instruction, not a caveat.** State it as: *if tier 2 ever appears not to fire on some application, check `WarmUp.opens` before anything else — a count in the dozens means the app is recreating its top-level window faster than the budget and warm-up is re-opening forever.* Unmeasured, and named as unmeasured. It must not be rediscovered by debugging OCR.
  2. **The measurement limitations, migrated verbatim in substance from spec §8:** Slack and Teams untested; the Discord figure rests on a **single** valid run (the two that preceded it measured the updater window, not the app); Chrome's fluctuation data came from an already-loaded page with a cold accessibility tree, not from a cold application start. A future reader must be able to see what the 2.0 s number does and does not rest on without going to the spec folder.

- [ ] **Step 2: Update `FLOW.md`**

The tier-2 request path now runs through `WarmUp.allows_tier2`, and `Observation` carries `target_hwnd`. Update the call graph and move the "you are here" marker.

- [ ] **Step 3: Update the tier-2 paragraph in `CLAUDE.md`**

It currently says tier 2 "is triggered by grounding failure for the current step". That is now qualified: grounding failure **outside a new window's warm-up**. One or two sentences; do not restate the whole design.

- [ ] **Step 4: Independent review — D032, ENFORCED GATE**

These docs must be read by something other than whoever wrote them before they are treated as correct. On this project three of four documentation defects in one milestone were in the single self-reviewed slice, and an uncited number reached the docs as fact. Dispatch a reviewer against the spec and the findings doc, and fix what it finds.

- [ ] **Step 5: Commit**

```bash
git add DECISIONS.md FLOW.md CLAUDE.md
git commit -m "docs: record the warm-up decision and update the flow"
git push origin main
```

---

## Self-Review

**Spec coverage.** §3 warm-up window → Tasks 1 and 3. §3 HWND keying → Task 1 (`allows_tier2`) + Task 2 (the handle crossing the boundary) + Task 3 (the call site). §3 budget as a constructor parameter → Task 1 `budget_s`, threaded through `run_tour(warmup_budget_s=...)`. §5 error handling: absent target → `test_absent_window_does_not_suppress`; grounding succeeds → `note_grounded`; expiry → `test_a_window_that_never_grounds...`; splash → both splash tests. §6 testing: all six bullets have a named test, except the non-monotonic-count bullet, which needs none — no comparison exists in the code to break. That is a property of the design, and the plan does not pretend otherwise by writing a decorative test for it.

**Not covered, deliberately.** §4's staleness third case. A not-yet-ready observation still feeds the ladder exactly as today. The spec itself says the distinction is unobservable during a first step (there is no hint on screen) and becomes real only if a target restarts mid-tour. Implementing it here would add a second class of event to D023's successful-observation bucket for no user-visible gain. **This is a scope decision, not an oversight — if a reviewer wants it, it is a fifth task, not a silent addition to a third.**

**Placeholder scan.** No TBDs. Every code step carries real code. The one deferral is Task 3 Step 1's harness, which points at `tests/test_freshness_timeline.py` and specifies the exact required surface — deliberate, because inventing a second `run_tour` driver when one exists is the wrong outcome.

**Type consistency.** `allows_tier2(hwnd: int) -> bool` and `note_grounded(hwnd: int) -> None` are used with those names and types in Tasks 1 and 3. `Observation.target_hwnd: int` is defined in Task 2 and read in Task 3. `hwnd_source: Callable[[str], int]` matches `first_matching_hwnd(title_re: str) -> int`. `DEFAULT_WARMUP_BUDGET_S` is defined once and imported by both `run.py` and the tests.
