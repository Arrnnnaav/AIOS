# Wrong-Action Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell the user when they act on the wrong control, and re-assert the hint, instead of dwelling in silence.

**Architecture:** The perception worker samples UIA focus in ~50 ms slices between its walks and publishes the distinct in-app AutomationIds focus *visited* since the last observation. The tick loop compares that list against the grounded target and, when verification is unsatisfied, prints one line and returns to `OBSERVING` — which re-grounds and re-shows the ring through the existing render path. The worker never learns what the current step is; the loop never touches UIA.

**Tech Stack:** Python 3.12, pywin32, comtypes (already present via pywinauto), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-wrong-action-feedback-design.md`

## Global Constraints

- **Only primitives cross the thread boundary** (D021). Focus crosses as `str` and `tuple[str, ...]`. No COM object, ever.
- **The `IUIAutomation` instance MUST be thread-local.** A module-level singleton created on one thread and used from the worker's apartment is the exact D021 failure — apartment-bound objects crossing threads give confusing intermittent failures, not clean errors.
- **The worker perceives; the tick loop decides** (D028). The worker filters only on process and on "has an AutomationId". It never learns which step is current.
- **No second overlay write path** (D027). The wrong-action branch must NOT call `renderer.show()`. It transitions to `OBSERVING` and lets the existing path re-hint.
- **Ordered-sequence tests on an injected clock** (D026). Never assert end state for time-dependent behaviour.
- **Mutation-verify** (D018), and state property vs invariant (D031).
- Focus cap: **8** ids per observation. Wrong-action re-hint cap: **3** per step. Idle re-hint cap stays **1**.
- **Commit as soon as your tests pass**, before mutation work. Six subagents have been lost to capacity limits on this project; every one that committed early kept its work.
- Windows-only. Never move the real cursor or synthesise input (D006).

## File Structure

| File | Responsibility |
|---|---|
| `ghostcursor/perception/focus.py` *(new)* | Reading UIA focus: thread-local automation object, process filter, AutomationId extraction. No knowledge of steps, walks or observations. |
| `tests/test_focus.py` *(new)* | Unit tests for the reader against a real `SyntheticApp` window. |
| `ghostcursor/perception/service.py` | Sliced inter-walk wait that accumulates visited ids; publishes `Observation.focus_visited` and fills `Snapshot.focused_automation_id`. |
| `tests/test_focus_service.py` *(new)* | Worker-side accumulation, with an injected fake focus reader. |
| `ghostcursor/reasoning/loop.py` | The wrong-action branch, its cap, and the `focus_visited_source` callable. |
| `tests/test_wrong_action.py` *(new)* | Loop decision tests, including every silence case. |
| `ghostcursor/run.py` | Supplies `focus_visited_source` from the published slot; prints the console lines. |
| `ghostcursor/reasoning/verification.py` | Enables `FOCUS_MOVES_TO` (Task 5 only). |

---

### Task 1: The focus reader

**Files:**
- Create: `ghostcursor/perception/focus.py`
- Test: `tests/test_focus.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `read_focused_automation_id(hwnd: int) -> str` — the AutomationId of the currently focused element, but only when focus is inside `hwnd`'s process and the element has a non-empty AutomationId; `""` in every other case, including on error.

**Property this protects:** the system never accuses the user of touching a control it cannot name.
**Invariant enforced:** `read_focused_automation_id` returns `""` unless focus is in-process with a non-empty id.
**Does the invariant imply the property?** Yes for this layer, because every caller treats `""` as "no information". Task 3 must preserve that by never firing on `""`.

- [ ] **Step 1: Write the failing tests**

```python
"""The focus reader: what UIA says has focus, filtered to the target process.

MOST OF THIS FILE IS DELIBERATELY NOT A REAL-FOCUS TEST, and that is a
correction to an earlier version of this plan which specified only real-focus
tests. They could not pass reliably: taking focus requires
`SetForegroundWindow`, and Windows' foreground lock REFUSES it for a process
that is not already frontmost. It succeeded in an interactive probe and then
failed under pytest with `pywintypes.error: (0, 'SetForegroundWindow')`, which
would also fail in CI and any time the terminal is not frontmost.

So the POLICY -- the process filter, the empty-id rule, the never-raise
contract -- is tested deterministically against a fake automation object, and
the environmental claim gets one real-window test that SKIPS honestly when the
OS refuses foreground. A test that only passes when a human happens to be
looking at the right window is not a test.

The real-focus equivalence claim (focus reports the same AutomationId a tree
walk reports: 1001/1002/1004 matched exactly) is recorded in the design spec
section 2.2 as a measurement, which is the right home for a fact about one
machine.
"""

import time

import pytest
import win32gui

from ghostcursor.overlay import dpi  # noqa: F401  -- DPI before any window (D010)
from ghostcursor.perception import focus as focus_module
from ghostcursor.perception.focus import read_focused_automation_id
from tests.uia_app import BTN_EXPORT, SyntheticApp

TARGET_HWND = 4242
TARGET_PID = 777


class _FakeElement:
    def __init__(self, pid: int, aid: str) -> None:
        self.CurrentProcessId = pid
        self.CurrentAutomationId = aid


class _FakeAutomation:
    def __init__(self, element) -> None:
        self._element = element

    def GetFocusedElement(self):
        if isinstance(self._element, Exception):
            raise self._element
        return self._element


@pytest.fixture
def wired(monkeypatch):
    """Point the reader at a fake focused element and a known process."""

    def _wire(element):
        monkeypatch.setattr(
            focus_module, "_automation", lambda: _FakeAutomation(element)
        )
        monkeypatch.setattr(focus_module, "_process_id_for", lambda hwnd: TARGET_PID)

    return _wire


def test_reports_the_id_when_focus_is_in_the_target_process(wired):
    wired(_FakeElement(TARGET_PID, "1001"))
    assert read_focused_automation_id(TARGET_HWND) == "1001"


def test_silent_when_focus_is_in_another_process(wired):
    """Alt-tabbing to Slack is not a mis-click and must never be reported as
    one."""
    wired(_FakeElement(TARGET_PID + 1, "1001"))
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_silent_when_the_focused_control_has_no_automation_id(wired):
    """Common in Chromium and Acrobat. We can see focus moved but cannot name
    where, and naming is the whole point: never accuse without naming."""
    wired(_FakeElement(TARGET_PID, ""))
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_silent_when_there_is_no_focused_element(wired):
    wired(None)
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_never_raises_when_the_automation_call_fails(wired):
    """The caller is the perception worker, whose product is the walk. Focus
    is a nicety and must never cost an observation."""
    wired(OSError("UIA exploded"))
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_silent_for_a_dead_window_handle():
    """No monkeypatching: the guard must fire before anything is consulted."""
    assert read_focused_automation_id(0) == ""
    assert read_focused_automation_id(-1) == ""


def test_silent_when_the_window_has_no_process(monkeypatch):
    monkeypatch.setattr(focus_module, "_process_id_for", lambda hwnd: 0)
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_against_a_real_window_when_the_os_permits_foreground():
    """The one genuinely end-to-end check. SKIPS rather than fails when
    Windows' foreground lock refuses -- a process that is not already
    frontmost cannot take focus, and that is OS policy, not a defect here."""
    with SyntheticApp(title="GhostCursorFocusRead") as app:
        for _ in range(40):
            app.pump()
            time.sleep(0.005)
        try:
            win32gui.SetForegroundWindow(app.hwnd)
        except Exception as exc:
            pytest.skip(f"OS refused foreground, cannot test real focus: {exc}")
        win32gui.SetFocus(win32gui.GetDlgItem(app.hwnd, BTN_EXPORT))
        for _ in range(40):
            app.pump()
            time.sleep(0.005)
        assert read_focused_automation_id(app.hwnd) == str(BTN_EXPORT)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_focus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostcursor.perception.focus'`

- [ ] **Step 3: Write the implementation**

```python
"""Reading which control currently has keyboard focus.

Wrong-action feedback needs to know that the user interacted with something,
and WHICH something. Focus is the right signal for that: it changes because a
user acted on a control, where the element set churns on its own -- VS Code's
element identity was measured fluctuating in steady state with no user action
at all (2026-08-19-cold-electron-probe-findings.md, section 3). A signal that
fires when the user did nothing is worse than no signal.

This module answers ONE question and knows nothing about steps, recipes or
grounding: which in-process AutomationId has focus right now, or "".
"""

from __future__ import annotations

import threading

#: The IUIAutomation instance, PER THREAD. This is not an optimisation.
#: UIA objects are apartment-bound (D021): one instance created on the UI
#: thread and then used from the perception worker gives confusing
#: intermittent failures rather than a clean error. threading.local() makes
#: "the object belongs to the thread that made it" structural instead of a
#: convention someone has to remember.
_local = threading.local()

_CLSID_CUIAutomation = "{ff48dba4-60ef-4201-aa87-54103eef594e}"


def _automation():
    existing = getattr(_local, "uia", None)
    if existing is not None:
        return existing
    import comtypes.client

    module = comtypes.client.GetModule("UIAutomationCore.dll")
    _local.uia = comtypes.client.CreateObject(
        _CLSID_CUIAutomation, interface=module.IUIAutomation
    )
    return _local.uia


def _process_id_for(hwnd: int) -> int:
    """Owning process of `hwnd`, or 0.

    A module-level function rather than an inline import so a test can
    substitute it without needing a real window AND a real foreground grab --
    see tests/test_focus.py on why real focus cannot be taken reliably.
    """
    try:
        import win32process

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return int(pid or 0)
    except Exception:
        return 0


def read_focused_automation_id(hwnd: int) -> str:
    """AutomationId of the focused control, if it is inside `hwnd`'s process.

    Returns "" for every case we cannot act on, and never raises:

    * focus is in another process -- the user alt-tabbed away, which is not a
      mis-click and must not be reported as one
    * the focused element has no AutomationId -- common in Chromium and
      Acrobat. We can see that focus moved but cannot name where, and naming
      is the whole point: never accuse without naming.
    * anything at all went wrong. The caller is the perception worker, whose
      product is the walk; focus is a nicety and must never cost an
      observation.
    """
    if hwnd <= 0:
        return ""
    try:
        target_pid = _process_id_for(hwnd)
        if not target_pid:
            return ""
        element = _automation().GetFocusedElement()
        if element is None or element.CurrentProcessId != target_pid:
            return ""
        return element.CurrentAutomationId or ""
    except Exception:
        return ""
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `python -m pytest tests/test_focus.py -v`
Expected: 7 passed, plus the real-window test passed or skipped.

- [ ] **Step 5: Commit — now, before the mutation work**

```bash
git add ghostcursor/perception/focus.py tests/test_focus.py
git commit -m "feat: read the focused control's AutomationId, in-process only"
git push origin <branch>
```

- [ ] **Step 6: Mutation-verify (D018), one at a time, reverting between**

| # | Mutation | Must fail |
|---|---|---|
| 1 | Delete the `CurrentProcessId != target_pid` check | `test_silent_when_focus_is_in_another_process` |
| 2 | `return element.CurrentAutomationId or "x"` | `test_silent_when_the_focused_control_has_no_automation_id` |
| 3 | Delete the `if hwnd <= 0: return ""` guard | `test_silent_for_a_dead_window_handle` |
| 4 | Replace `except Exception: return ""` with a bare `raise` | `test_never_raises_when_the_automation_call_fails` |

Every mutation must fail a DETERMINISTIC test. If one only changes the result
of the skippable real-window test, it is NOT verified — say so rather than
counting it. An earlier run of this task recorded a mutation as caught when the
baseline was already failing those same tests, which proved nothing.

Record each result, naming the test that caught it, in `docs/superpowers/ledgers/2026-08-20-wrong-action-feedback-ledger.md` (create it). Per D034, "mutation-verified" must name where it is recorded.

- [ ] **Step 7: Commit the ledger**

```bash
git add docs/superpowers/ledgers/2026-08-20-wrong-action-feedback-ledger.md
git commit -m "docs: record focus reader mutation results"
git push origin <branch>
```

---

### Task 2: The worker samples focus between walks

**Files:**
- Modify: `ghostcursor/perception/service.py` — `Observation`, `PerceptionService.__init__`, `_run`
- Modify: `ghostcursor/reasoning/verification.py` — `take_snapshot` signature
- Test: `tests/test_focus_service.py` *(new)*

**Interfaces:**
- Consumes: `read_focused_automation_id(hwnd: int) -> str` (Task 1).
- Produces: `Observation.focus_visited: tuple[str, ...]`; `PerceptionService(..., focus_reader: Callable[[int], str] = read_focused_automation_id, focus_slice_s: float = 0.05)`; `take_snapshot(..., focused_automation_id: str = "")`.

**Why the slices:** the worker refreshes every `REFRESH_SECONDS = 0.25` plus a walk of 0.18–0.70 s, so focus sampled once per walk lands every 0.4–1.0 s. A user who clicks the wrong control and corrects themselves does it in well under a second — the case FOLLOWUPS names first. Slicing the *wait* costs 1–3 ms per sample and catches it.

- [ ] **Step 1: Write the failing tests**

```python
"""The worker accumulates which controls focus VISITED between observations.

Resting focus is not enough. The motivating case is a wrong click the user
corrects themselves, where focus has already moved on by the time the next
walk completes -- so the worker records what focus touched during the wait,
not where it ended up.
"""

import time

from ghostcursor.perception.service import PerceptionService


def _wait_for(service, predicate, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        observation = service.latest()
        if observation is not None and predicate(observation):
            return observation
        time.sleep(0.01)
    raise AssertionError("condition never held within the timeout")


def test_focus_visited_records_ids_seen_during_the_wait():
    """Focus moves to 'b' and back to 'a' between walks. Both must be
    recorded -- recording only the final value is exactly the miss this
    slicing exists to prevent."""
    sequence = iter(["a", "b", "a", "a", "a", "a", "a", "a"])

    def reader(_hwnd):
        try:
            return next(sequence)
        except StopIteration:
            return "a"

    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=reader,
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        observation = _wait_for(service, lambda o: "b" in o.focus_visited)
    finally:
        service.stop()
    assert "b" in observation.focus_visited


def test_empty_ids_are_never_recorded():
    """'' means 'focus is somewhere we cannot name'. It must never enter the
    list, or the loop would compare against it and could report a wrong
    action it cannot describe."""
    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=lambda _hwnd: "",
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        observation = _wait_for(service, lambda o: o.observed_at > 0)
    finally:
        service.stop()
    assert observation.focus_visited == ()


def test_focus_visited_is_capped_and_deduplicated():
    """A control cycling focus must not grow the payload without bound."""
    counter = iter(range(1000))
    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=lambda _hwnd: f"id{next(counter)}",
        focus_slice_s=0.001,
        interval_s=0.2,
    )
    service.start()
    try:
        observation = _wait_for(service, lambda o: len(o.focus_visited) > 0)
    finally:
        service.stop()
    assert len(observation.focus_visited) <= 8
    assert len(set(observation.focus_visited)) == len(observation.focus_visited)


def test_focus_visited_resets_between_observations():
    """Each observation describes the interval that produced it. Carrying ids
    forward would let one wrong click be reported on every later tick."""
    calls = {"n": 0}

    def reader(_hwnd):
        calls["n"] += 1
        return "early" if calls["n"] <= 2 else ""

    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=reader,
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        _wait_for(service, lambda o: "early" in o.focus_visited)
        later = _wait_for(
            service,
            lambda o: o.focus_visited == () and calls["n"] > 10,
        )
    finally:
        service.stop()
    assert later.focus_visited == ()


def test_a_raising_focus_reader_does_not_kill_the_walk():
    """The walk is the product; focus is a nicety."""

    def boom(_hwnd):
        raise OSError("focus exploded")

    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=boom,
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        observation = _wait_for(service, lambda o: o.ok)
    finally:
        service.stop()
    assert observation.ok is True
    assert observation.focus_visited == ()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_focus_service.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'focus_reader'`

- [ ] **Step 3: Widen `take_snapshot` in `ghostcursor/reasoning/verification.py`**

Change the signature to accept the focused id and stop hardcoding it. Find:

```python
        focused_automation_id="",
```

Replace the whole function's handling by adding a parameter to its signature — `focused_automation_id: str = ""` — and passing it through:

```python
        focused_automation_id=focused_automation_id,
```

The default keeps every existing caller and every collaborator fake working unchanged.

- [ ] **Step 4: Implement the worker changes in `ghostcursor/perception/service.py`**

Import the reader:

```python
from ghostcursor.perception.focus import read_focused_automation_id
```

Add the constants near the other module constants:

```python
#: How often focus is sampled during the inter-walk wait. Focus reads cost a
#: 2.66ms median, so this is cheap; it is 50ms because the case worth catching
#: is a wrong click the user corrects themselves, which happens far slower
#: than that. See the design spec, section 2.3.
DEFAULT_FOCUS_SLICE_S = 0.05
#: Ceiling on ids carried per observation, so a control that cycles focus
#: cannot grow the published payload without bound.
MAX_FOCUS_VISITED = 8
```

Add to `Observation`, after `target_hwnd`:

```python
    #: Distinct in-process AutomationIds that focus VISITED since the previous
    #: observation -- not where focus rests now. Resting is not enough: the
    #: case this exists for is a wrong click the user corrects before the next
    #: walk completes. Plain strings, because only primitives cross the worker
    #: boundary (D021). Empty ids are never recorded: "" means focus is
    #: somewhere we cannot name, and naming is the point.
    focus_visited: tuple[str, ...] = ()
```

Add the constructor parameters beside `hwnd_source`:

```python
        focus_reader: Callable[[int], str] = read_focused_automation_id,
        focus_slice_s: float = DEFAULT_FOCUS_SLICE_S,
```

and store them:

```python
        self.focus_reader = focus_reader
        self.focus_slice_s = focus_slice_s
```

Add these two methods to `PerceptionService`:

```python
    def _safe_focus(self, hwnd: int) -> str:
        """Never let a focus failure cost an observation."""
        try:
            return self.focus_reader(hwnd)
        except Exception:
            return ""

    def _sample_focus_while_waiting(
        self, stop: threading.Event, hwnd: int, visited: list[str]
    ) -> None:
        """Wait out `interval_s`, sampling focus in slices as it passes.

        Replaces a single `stop.wait(interval_s)`. Sampling at the WALK's
        cadence would land every 0.4-1.0s, and a user who clicks the wrong
        control and corrects themselves does it in well under a second -- the
        first of the two cases this feature exists for. Slicing the wait
        catches it for 1-3ms a sample.

        Still honours `stop` promptly: each slice is its own bounded wait, so
        a stopping worker leaves within one slice.
        """
        remaining = self.interval_s
        while remaining > 0 and not stop.is_set():
            slice_s = min(self.focus_slice_s, remaining)
            if stop.wait(slice_s):
                return
            remaining -= slice_s
            focused = self._safe_focus(hwnd)
            if (
                focused
                and focused not in visited
                and len(visited) < MAX_FOCUS_VISITED
            ):
                visited.append(focused)
```

In `_run`, initialise the accumulator immediately before the `while` loop:

```python
            visited: list[str] = []
```

Inside the walk's `try`, after `target_hwnd = self._safe_hwnd()`, capture the walk-time focus and pass it into the snapshot:

```python
                    focused_now = self._safe_focus(target_hwnd)
```

and give `take_snapshot` the new argument:

```python
                        take_snapshot(
                            self.title_re,
                            elements=elements,
                            observed_at=observed_at,
                            focused_automation_id=focused_now,
                        ),
```

Pass the accumulated list on the published `Observation`:

```python
                            focus_visited=tuple(visited),
```

Immediately after the `self._publish(...)` call, and ALSO on the path where nothing was published, clear the accumulator so each observation describes only its own interval:

```python
                visited.clear()
```

Place that clear directly after the `if walked is not None and not stop.is_set():` block, at the same indentation as that `if`, so it runs on every iteration.

Finally replace the tail of the loop:

```python
                stop.wait(self.interval_s)
```

with:

```python
                self._sample_focus_while_waiting(stop, target_hwnd_for_wait, visited)
```

where `target_hwnd_for_wait` is the handle from this iteration. Initialise it to `0` before the `try` so a failed walk still waits:

```python
                target_hwnd_for_wait = 0
```

and set it inside the `try` right after `target_hwnd = self._safe_hwnd()`:

```python
                    target_hwnd_for_wait = target_hwnd
```

- [ ] **Step 5: Run the new tests**

Run: `python -m pytest tests/test_focus_service.py -v`
Expected: 5 passed.

- [ ] **Step 6: Run the fast suite**

Run:
```bash
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
```
Expected: all pass. **Never run two pytest sessions at once, and never run those three files** — they park a non-pumping window that taxes UI Automation machine-wide, measured 6.28 s versus 100.13 s (D025). The controller runs them.

- [ ] **Step 7: Commit**

```bash
git add ghostcursor/perception/service.py ghostcursor/reasoning/verification.py tests/test_focus_service.py
git commit -m "feat: publish which controls focus visited between observations"
git push origin <branch>
```

- [ ] **Step 8: Mutation-verify (D018)**

| # | Mutation | Must fail |
|---|---|---|
| 1 | Sample focus only once per walk instead of in slices (delete the loop body's sampling, keep the wait) | `test_focus_visited_records_ids_seen_during_the_wait` |
| 2 | Delete `visited.clear()` | `test_focus_visited_resets_between_observations` |
| 3 | Drop the `len(visited) < MAX_FOCUS_VISITED` condition | `test_focus_visited_is_capped_and_deduplicated` |
| 4 | Drop the `focused and` condition so `""` is recorded | `test_empty_ids_are_never_recorded` |

Append the results to the ledger and commit.

---

### Task 3: The loop decides and speaks

**Files:**
- Modify: `ghostcursor/reasoning/loop.py` — `GuidedTour.__init__`, the `AWAITING_USER_ACTION` branch
- Test: `tests/test_wrong_action.py` *(new)*

**Interfaces:**
- Consumes: `Observation.focus_visited` (Task 2), reaching the loop through a callable.
- Produces: `GuidedTour(..., focus_visited_source: Callable[[], tuple[str, ...]] | None = None, on_wrong_action: Callable[[str, str], None] | None = None)`; `GuidedTour.wrong_action_rehints: int`.

**Why a callable rather than a field on `Snapshot`:** the loop only ever sees `Snapshot`, and `focus_visited` is an *interval* fact — what focus touched between looks — not a point-in-time one. Putting it on `Snapshot` would mix an interval into the value `verify()` diffs before against after. The codebase already has this exact split: `ungroundable_reason` is an injected callable owned by `run.py` for precisely the same reason, and `OverlayRenderer.freshness_source` is documented as existing because the caller that KNOWS is not the caller that DRIVES.

**Property this protects:** a user who acts on the wrong control is told, and the hint re-asserts.
**Invariant enforced:** a non-target in-app AutomationId in `focus_visited`, with verification unsatisfied, produces exactly one `on_wrong_action` call and a transition to `OBSERVING`.
**Does the invariant imply the property?** Only if `focus_visited` faithfully reflects what focus touched — which is why Task 2 has its own accumulation tests rather than relying on these.

- [ ] **Step 1: Write the failing tests**

```python
"""The loop's wrong-action decision.

Read tests/test_loop.py first for the collaborator-fake pattern this builds
on. Every fake here is deliberate: this file tests the DECISION, and Task 2
tests whether focus_visited is faithful. Neither test alone is sufficient
(D031) -- an invariant about a list only implies the property if the list is
faithful, and that is a different test.
"""

from ghostcursor.reasoning.loop import GuidedTour, State


def test_fires_when_focus_visited_a_non_target_control(wrong_action_tour):
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()

    h.set_focus_visited(("1002",))
    h.tick()

    assert h.wrong_actions == [("1002", "1001")]
    assert h.tour.state is State.OBSERVING


def test_silent_when_focus_visited_only_the_target(wrong_action_tour):
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()

    h.set_focus_visited(("1001",))
    h.tick()

    assert h.wrong_actions == []


def test_silent_when_nothing_was_focused(wrong_action_tour):
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()

    h.set_focus_visited(())
    h.tick()

    assert h.wrong_actions == []


def test_satisfied_wins_over_a_detour(wrong_action_tour):
    """The user touched the wrong control and then did the right thing. The
    step succeeded; interrupting a success to criticise it is the Clippy
    failure this loop is built to avoid."""
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()

    h.set_focus_visited(("1002",))
    h.satisfy_verification()
    h.tick()

    assert h.tour.state is State.VERIFYING
    assert h.wrong_actions == [], "scolded the user for a step they completed"


def test_silent_when_the_target_was_grounded_by_ocr(wrong_action_tour):
    """OCR elements carry no AutomationId, so there is nothing to compare
    against. Firing here would report a wrong action on every focus change."""
    h = wrong_action_tour(target_id="")
    h.arrive_at_awaiting()

    h.set_focus_visited(("1002",))
    h.tick()

    assert h.wrong_actions == []


def test_rehints_are_capped_at_three_but_messages_are_not(wrong_action_tour):
    """The cap counts RE-HINTS, not messages. Going quiet entirely would tell
    a user who keeps trying and failing less the harder they struggle, which
    is backwards for a teaching system."""
    h = wrong_action_tour(target_id="1001")
    seen = []
    for _ in range(5):
        h.arrive_at_awaiting()
        h.set_focus_visited(("1002",))
        h.tick()
        seen.append(h.tour.wrong_action_rehints)

    assert seen == [1, 2, 3, 3, 3], "re-hint counter is not capped at 3"
    assert len(h.wrong_actions) == 5, "stopped speaking after the re-hint cap"


def test_the_counter_resets_on_a_new_step(wrong_action_tour):
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()
    h.set_focus_visited(("1002",))
    h.tick()
    assert h.tour.wrong_action_rehints == 1

    h.complete_step()
    assert h.tour.wrong_action_rehints == 0, (
        "a previous step's fumbles are being counted against a fresh one"
    )
```

Write the `wrong_action_tour` fixture in the same file. Build it on the collaborator fakes already in `tests/test_loop.py` — read that file and reuse its recipe/renderer/verifier fakes rather than inventing a second set. The fixture must expose: `tour`, `arrive_at_awaiting()` (drive the tour to `AWAITING_USER_ACTION` with a grounded target whose `automation_id` is the given `target_id`), `set_focus_visited(ids)`, `satisfy_verification()`, `complete_step()`, `tick()`, and a `wrong_actions` list recording each `(touched_id, target_id)` pair passed to `on_wrong_action`.

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_wrong_action.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'focus_visited_source'`

- [ ] **Step 3: Add the constructor parameters in `ghostcursor/reasoning/loop.py`**

Add to `GuidedTour.__init__`, after `ungroundable_reason`:

```python
        focus_visited_source: Callable[[], tuple[str, ...]] | None = None,
        on_wrong_action: Callable[[str, str], None] | None = None,
```

Store them and the counter:

```python
        self.focus_visited_source = focus_visited_source
        self.on_wrong_action = on_wrong_action
        #: Wrong-action re-hints spent on the CURRENT step. Separate from
        #: rehint_count, which counts idle nudges: idle means the user is
        #: doing nothing and a second nudge is nagging, while a wrong action
        #: means they are actively trying and answering each attempt is help.
        self.wrong_action_rehints = 0
```

- [ ] **Step 4: Add the branch in `AWAITING_USER_ACTION`**

It goes AFTER the `if satisfied:` arm and BEFORE the `elif elements_changed(...)` arm, so that a satisfied step never scolds:

```python
            elif self._wrong_action(step) is not None:
                touched = self._wrong_action(step)
                # Speak every time -- the message is bounded by real user
                # actions, not by a clock, so it cannot nag the way an idle
                # timer can. Capping it would tell a user who keeps trying
                # and failing LESS the harder they struggle.
                if self.on_wrong_action is not None:
                    self.on_wrong_action(touched, self._target_automation_id())
                # Re-hint by going back through OBSERVING, NOT by calling
                # renderer.show() here. A second overlay write path is what
                # D027 exists to prevent: set_hint ends in UpdateWindow, which
                # paints synchronously, so an extra frame definitely reaches
                # the screen. OBSERVING also re-grounds, which is right on its
                # own terms -- a wrong click may have opened a dialog and
                # moved the target.
                if self.wrong_action_rehints < 3:
                    self.wrong_action_rehints += 1
                    self.state = State.OBSERVING
```

Add the two helpers as methods on `GuidedTour`:

```python
    def _target_automation_id(self) -> str:
        grounded = self._grounded
        return getattr(grounded, "automation_id", "") if grounded else ""

    def _wrong_action(self, step) -> str | None:
        """The first in-app control focus touched that is not the target.

        None when there is nothing to report. Silent by construction in every
        case the design names: no source wired, nothing visited, or a target
        with no AutomationId of its own -- which is what an OCR-grounded
        target is, since OCR elements carry no id. Comparing against "" there
        would report a wrong action on every focus change.
        """
        if self.focus_visited_source is None:
            return None
        target_id = self._target_automation_id()
        if not target_id:
            return None
        for touched in self.focus_visited_source():
            if touched and touched != target_id:
                return touched
        return None
```

Reset the counter where the step advances. In the `VERIFYING` arm, beside `self._confirmed = False`:

```python
            self.wrong_action_rehints = 0
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_wrong_action.py -v`
Expected: 7 passed.

- [ ] **Step 6: Run the fast suite**

Run:
```bash
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
```
Expected: all pass. If a pre-existing loop test breaks, **do not weaken its assertion** — the likely cause is the new branch firing in a test that did not expect it, and the correct fix is leaving `focus_visited_source` unwired (its default `None` makes the branch inert), not changing what the old test checks.

- [ ] **Step 7: Commit**

```bash
git add ghostcursor/reasoning/loop.py tests/test_wrong_action.py
git commit -m "feat: name the wrong control and re-assert the hint"
git push origin <branch>
```

- [ ] **Step 8: Mutation-verify (D018)**

| # | Mutation | Must fail |
|---|---|---|
| 1 | Delete the whole `elif self._wrong_action(step) is not None:` arm | `test_fires_when_focus_visited_a_non_target_control` |
| 2 | Move the arm ABOVE the `if satisfied:` arm | `test_satisfied_wins_over_a_detour` |
| 3 | Delete the `if not target_id: return None` guard | `test_silent_when_the_target_was_grounded_by_ocr` |
| 4 | Remove the `< 3` cap so it re-hints every time | `test_rehints_are_capped_at_three_but_messages_are_not` |
| 5 | Delete the counter reset in `VERIFYING` | `test_the_counter_resets_on_a_new_step` |
| 6 | Call `self.renderer.show(...)` in the branch instead of transitioning | Nothing here catches this — it is a D027 violation, not a behaviour change. **Report that honestly** rather than inventing a passing test; the guard against it is review, and this row exists to say so. |

Append results to the ledger, including row 6's honest negative, and commit.

---

### Task 4: Wire it into `run.py`

**Files:**
- Modify: `ghostcursor/run.py` — the `run_tour` body where `GuidedTour` is constructed (~line 519)
- Test: `tests/test_wrong_action_tour.py` *(new)*

**Interfaces:**
- Consumes: `Observation.focus_visited` (Task 2); `focus_visited_source` and `on_wrong_action` (Task 3).
- Produces: no new public surface.

- [ ] **Step 1: Write the failing test**

```python
"""Wrong-action feedback end to end through run_tour, with a fake service.

Mirrors tests/test_freshness_timeline.py -- read it for the harness shape and
reuse its driver rather than writing a second one.
"""


def test_a_wrong_action_prints_once_and_re_asserts_the_hint(tour_harness):
    h = tour_harness(target_id="1001")
    h.publish_observation(focus_visited=("1002",))
    h.tick()

    assert any("1002" in line for line in h.printed), (
        "the user was never told which control they touched"
    )


def test_no_line_when_focus_stayed_on_the_target(tour_harness):
    h = tour_harness(target_id="1001")
    h.publish_observation(focus_visited=("1001",))
    h.tick()

    assert not any("1002" in line for line in h.printed)
```

Build `tour_harness` on the existing `run_tour` driver in `tests/test_freshness_timeline.py`, capturing `print` via monkeypatch the way that file already does. It must expose `publish_observation(focus_visited=...)`, `tick()`, and a `printed` list.

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/test_wrong_action_tour.py -v`
Expected: FAIL — nothing is printed.

- [ ] **Step 3: Wire it in `run.py`**

Next to the other closures that read the published slot, add:

```python
            def focus_visited_source():
                observation = service.latest()
                return observation.focus_visited if observation is not None else ()

            def on_wrong_action(touched: str, target: str) -> None:
                # The console is the RECORD; the ring is the correction. The
                # user is looking at their application, not at this terminal,
                # so the ring re-asserting through OBSERVING is what they
                # actually see -- this line is what explains it afterwards.
                print(
                    f"  that was {touched!r}, not {target!r} — "
                    "re-showing the hint on the right control"
                )
```

Pass both into the `GuidedTour(...)` construction:

```python
                focus_visited_source=focus_visited_source,
                on_wrong_action=on_wrong_action,
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_wrong_action_tour.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the fast suite, then commit**

```bash
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
git add ghostcursor/run.py tests/test_wrong_action_tour.py
git commit -m "feat: wire wrong-action feedback into the tour"
git push origin <branch>
```

---

### Task 5: Enable `FOCUS_MOVES_TO`

**Files:**
- Modify: `ghostcursor/reasoning/verification.py` — the `FOCUS_MOVES_TO` arm of `verify()`
- Test: `tests/test_verification.py` (extend)

**Interfaces:**
- Consumes: `Snapshot.focused_automation_id`, now genuinely populated (Task 2).
- Produces: no new surface; a verification kind that previously raised now works.

**Why it is its own task:** this milestone removed the blocker that the `NotImplementedError` names. Leaving a deliberate "not implemented because X" raise after X is fixed makes the codebase lie about itself and costs the next reader an investigation to find the note is stale. It is separate because a verification kind that advances a tour deserves its own coverage rather than riding in on a feature that merely happens to unblock it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verification.py`:

```python
def test_focus_moves_to_passes_when_focus_lands_on_the_named_control():
    rule = VerificationRule(
        kind=VerificationKind.FOCUS_MOVES_TO, args={"automation_id": "1004"}
    )
    before = Snapshot(title="t", elements=(), focused_automation_id="1001")
    after = Snapshot(title="t", elements=(), focused_automation_id="1004")
    assert verify(rule, before, after) is True


def test_focus_moves_to_fails_when_focus_did_not_move():
    rule = VerificationRule(
        kind=VerificationKind.FOCUS_MOVES_TO, args={"automation_id": "1004"}
    )
    same = Snapshot(title="t", elements=(), focused_automation_id="1004")
    assert verify(rule, same, same) is False, (
        "focus already there is not focus MOVING there -- a step would "
        "self-satisfy before the user did anything"
    )


def test_focus_moves_to_fails_when_focus_landed_elsewhere():
    rule = VerificationRule(
        kind=VerificationKind.FOCUS_MOVES_TO, args={"automation_id": "1004"}
    )
    before = Snapshot(title="t", elements=(), focused_automation_id="1001")
    after = Snapshot(title="t", elements=(), focused_automation_id="1002")
    assert verify(rule, before, after) is False


def test_focus_moves_to_fails_when_focus_is_unknown():
    """'' means focus could not be named. Treating it as a match would let a
    step pass on no evidence."""
    rule = VerificationRule(
        kind=VerificationKind.FOCUS_MOVES_TO, args={"automation_id": ""}
    )
    before = Snapshot(title="t", elements=(), focused_automation_id="1001")
    after = Snapshot(title="t", elements=(), focused_automation_id="")
    assert verify(rule, before, after) is False
```

- [ ] **Step 2: Run and verify they fail**

Run: `python -m pytest tests/test_verification.py -v -k focus_moves_to`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Replace the raise**

```python
    if kind is VerificationKind.FOCUS_MOVES_TO:
        # Focus tracking exists now: the worker samples it and take_snapshot
        # carries it (see the wrong-action feedback milestone). Until then
        # this raised, because focused_automation_id was hardcoded "" and the
        # rule would have silently returned False forever.
        #
        # MOVES to, not IS at: a step whose target already has focus must not
        # satisfy itself before the user has done anything. "" is never a
        # match -- it means focus could not be named, which is no evidence.
        wanted = args["automation_id"]
        if not wanted:
            return False
        return before.focused_automation_id != wanted and (
            after.focused_automation_id == wanted
        )
```

- [ ] **Step 4: Run the tests, then the fast suite, then commit**

```bash
python -m pytest tests/test_verification.py -v
python -m pytest tests/ --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py -q
git add ghostcursor/reasoning/verification.py tests/test_verification.py
git commit -m "feat: enable FOCUS_MOVES_TO now that focus is tracked"
git push origin <branch>
```

- [ ] **Step 5: Mutation-verify (D018)**

| # | Mutation | Must fail |
|---|---|---|
| 1 | `return after.focused_automation_id == wanted` (drop the "moved" half) | `test_focus_moves_to_fails_when_focus_did_not_move` |
| 2 | Delete the `if not wanted: return False` guard | `test_focus_moves_to_fails_when_focus_is_unknown` |

Append to the ledger and commit.

---

### Task 6: Documentation

**Files:**
- Modify: `DECISIONS.md`, `FLOW.md`, `CLAUDE.md`

- [ ] **Step 1: Add the decision entry**

Append to `DECISIONS.md` as the next free number (**check, do not assume** — D036 is the last at time of writing). It must state: that focus, not `elements_changed`, is the signal, and why — VS Code's element identity churns in steady state with no user action, cited to `docs/superpowers/specs/2026-08-19-cold-electron-probe-findings.md` §3; the measured focus numbers (2.66 ms median; ids 1001/1002/1004 matching the tree walk exactly) cited to `docs/superpowers/specs/2026-08-20-wrong-action-feedback-design.md` §2, **which is their primary record** (D034); the worker/loop split (D028); that the re-hint reuses `OBSERVING` rather than adding a second write path (D027); the 3-cap for wrong-action re-hints against the 1-cap for idle, and why they differ; and the OCR blind spot stated as a plain property.

- [ ] **Step 2: Update `FLOW.md`**

The worker now samples focus between walks and publishes `focus_visited`; `AWAITING_USER_ACTION` has a new arm between the satisfied and `elements_changed` arms; `run.py` supplies `focus_visited_source` and `on_wrong_action`. Update the call graph and move the "you are here" marker.

- [ ] **Step 3: Update `CLAUDE.md`**

Add two or three sentences to the reasoning section: the loop now names a wrong action and re-asserts the hint, keyed on focus rather than element churn, and it is silent on OCR-grounded steps. Do not restate the design.

- [ ] **Step 4: Independent review — D032, ENFORCED GATE**

These docs must be read by something other than whoever wrote them. On an earlier milestone three of four documentation defects were in the single self-reviewed slice, and an uncited number reached the docs as fact. Per D036, when a defect is found, **sweep for siblings before closing it** — the last milestone shipped a corrected docstring while its identical twin survived in another file and reached the pull request.

- [ ] **Step 5: Commit**

```bash
git add DECISIONS.md FLOW.md CLAUDE.md
git commit -m "docs: record the wrong-action feedback decision"
git push origin <branch>
```

---

## Self-Review

**Spec coverage.** §2 signal → Task 1. §2.3 sampling rate → Task 2's slices. §3.1 worker-perceives-only → Task 1's process filter plus Task 2's accumulation; the worker never receives step context in any task. §3.2 boundary fields → Task 2 (`focus_visited`) and Task 2 Step 3 (`focused_automation_id`). §3.3 ordering → Task 3 Step 4, mutation 2 guards it. §3.4 no second write path → Task 3, and mutation row 6 records honestly that no test catches a violation. §3.5 caps → Task 3's cap tests. §4 silence cases → one test each in Tasks 1 and 3. §5 testing → the worker's accumulation has its own tests, per the D031 note. §6 `FOCUS_MOVES_TO` → Task 5. §7 deferred native events → not implemented, by design.

**Placeholder scan.** No TBDs. Two fixtures are specified by required surface rather than written out — `wrong_action_tour` (Task 3) and `tour_harness` (Task 4) — both pointing at the existing file to build on. Deliberate: inventing a second `run_tour` driver when one exists is the wrong outcome, and the last milestone proved a hand-rolled harness is where the subtle bugs land.

**Type consistency.** `read_focused_automation_id(hwnd: int) -> str` is defined in Task 1 and consumed as `focus_reader: Callable[[int], str]` in Task 2. `Observation.focus_visited: tuple[str, ...]` is defined in Task 2 and read in Tasks 3 and 4. `focus_visited_source: Callable[[], tuple[str, ...]]` and `on_wrong_action: Callable[[str, str], None]` are defined in Task 3 and supplied in Task 4. `take_snapshot(..., focused_automation_id: str = "")` is widened in Task 2 and consumed in Task 5.

**One risk worth naming for the executor.** Task 2 touches the perception worker's loop, which is the most carefully-reasoned code in this repo (D021, D022, D024). The `visited.clear()` placement is the subtle part: too early and one interval's ids leak into the next observation, too late and they leak forward a tick. Task 2's `test_focus_visited_resets_between_observations` is the test that catches it, and mutation 2 proves that test works.
