# Mutation ledger — Task 1: the focus reader

Plan: `.superpowers/sdd/2026-08-20-wrong-action-feedback/task-1-brief.md`
Branch: `wrong-action-feedback`
Files: `ghostcursor/perception/focus.py`, `tests/test_focus.py`
Baseline commit (7 deterministic tests passing, 1 real-window test skipped): `e1b8506`

The prior attempt (`b2a67cd`) recorded mutation results against a baseline
that was already failing 2 of 4 tests under pytest (real focus taken via
`SetForegroundWindow`, refused by Windows' foreground lock for a
non-frontmost process). That proved nothing. This ledger's baseline was
confirmed green with `python -m pytest tests/test_focus.py -v` three
consecutive times before any mutation was applied (see task-1-report.md).

Per D018, each mutation below was applied to `ghostcursor/perception/focus.py`
one at a time, verified against `python -m pytest tests/test_focus.py -v`,
then reverted with `git checkout -- ghostcursor/perception/focus.py` before
the next mutation.

## Results

| # | Mutation | Must fail | Actually failed | Result |
|---|---|---|---|---|
| 1 | Delete the `CurrentProcessId != target_pid` check | `test_silent_when_focus_is_in_another_process` | `test_silent_when_focus_is_in_another_process` (1 of 8) | PASS — verified |
| 2 | `return element.CurrentAutomationId or "x"` | `test_silent_when_the_focused_control_has_no_automation_id` | `test_silent_when_the_focused_control_has_no_automation_id` (1 of 8) | PASS — verified |
| 3 | Delete the `if hwnd <= 0: return ""` guard | `test_the_hwnd_guard_holds_even_if_the_process_lookup_succeeds` (added after the fact — see below) | that test (1 of 9) | PASS — verified |
| 4 | Replace `except Exception: return ""` with a bare `raise` | `test_never_raises_when_the_automation_call_fails` | `test_never_raises_when_the_automation_call_fails` (1 of 8) | PASS — verified |

## Mutation 1 failure output (verbatim)

```
tests/test_focus.py::test_silent_when_focus_is_in_another_process FAILED

________________ test_silent_when_focus_is_in_another_process _________________

wired = <function wired.<locals>._wire at 0x000001DED3061260>

    def test_silent_when_focus_is_in_another_process(wired):
        """Alt-tabbing to Slack is not a mis-click and must never be reported as
        one."""
        wired(_FakeElement(TARGET_PID + 1, "1001"))
>       assert read_focused_automation_id(TARGET_HWND) == ""
E       AssertionError: assert '1001' == ''
E
E         + 1001

tests\test_focus.py:75: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_focus.py::test_silent_when_focus_is_in_another_process - As...
========================= 1 failed, 7 passed in 0.94s =========================
```

## Mutation 2 failure output (verbatim)

```
tests/test_focus.py::test_silent_when_the_focused_control_has_no_automation_id FAILED

__________ test_silent_when_the_focused_control_has_no_automation_id __________

wired = <function wired.<locals>._wire at 0x0000023215581440>

    def test_silent_when_the_focused_control_has_no_automation_id(wired):
        """Common in Chromium and Acrobat. We can see focus moved but cannot name
        where, and naming is the whole point: never accuse without naming."""
        wired(_FakeElement(TARGET_PID, ""))
>       assert read_focused_automation_id(TARGET_HWND) == ""
E       AssertionError: assert 'x' == ''
E
E         + x

tests\test_focus.py:82: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_focus.py::test_silent_when_the_focused_control_has_no_automation_id
========================= 1 failed, 7 passed in 0.94s =========================
```

## Mutation 3 — history and final result

Deleting the `if hwnd <= 0: return ""` guard was **initially unverifiable**:
against the original 8-test file it did not fail any test — `8 passed` (all
deterministic tests, plus the real-window test, which happened to pass
rather than skip on that run):

```
tests/test_focus.py::test_reports_the_id_when_focus_is_in_the_target_process PASSED [ 12%]
tests/test_focus.py::test_silent_when_focus_is_in_another_process PASSED [ 25%]
tests/test_focus.py::test_silent_when_the_focused_control_has_no_automation_id PASSED [ 37%]
tests/test_focus.py::test_silent_when_there_is_no_focused_element PASSED [ 50%]
tests/test_focus.py::test_never_raises_when_the_automation_call_fails PASSED [ 62%]
tests/test_focus.py::test_silent_for_a_dead_window_handle PASSED         [ 75%]
tests/test_focus.py::test_silent_when_the_window_has_no_process PASSED   [ 87%]
tests/test_focus.py::test_against_a_real_window_when_the_os_permits_foreground PASSED [100%]

============================== 8 passed in 0.79s ==============================
```

Root cause: `test_silent_for_a_dead_window_handle` does not monkeypatch
`_process_id_for` — it calls `read_focused_automation_id(0)` and
`read_focused_automation_id(-1)` against the real function. With the
`hwnd <= 0` guard removed, execution falls through to
`_process_id_for(hwnd)`, which calls the real
`win32process.GetWindowThreadProcessId(hwnd)`. For both `hwnd=0` and
`hwnd=-1` that call itself fails (invalid handle), which
`_process_id_for`'s own `except Exception: return 0` swallows, so
`target_pid` is `0` either way and the function still returns `""` — for
the wrong reason, via a second, coincidentally-overlapping guard rather
than the one the brief specifies. This history is worth keeping: it is the
useful part, and the reason the guard needed a purpose-built test rather
than being trusted to the existing one.

Per the same reasoning as D030 (an explicit provenance guard kept despite
being redundant, because the redundancy rested on a coincidence a later
tier could break), the guard was kept and a new test was added —
`test_the_hwnd_guard_holds_even_if_the_process_lookup_succeeds` — that
forces `_process_id_for` to answer for a bogus handle (via monkeypatch),
removing the coincidental overlap. Re-running mutation 3 against the
9-test file now fails exactly that test and nothing else:

```
tests/test_focus.py::test_reports_the_id_when_focus_is_in_the_target_process PASSED [ 11%]
tests/test_focus.py::test_silent_when_focus_is_in_another_process PASSED [ 22%]
tests/test_focus.py::test_silent_when_the_focused_control_has_no_automation_id PASSED [ 33%]
tests/test_focus.py::test_silent_when_there_is_no_focused_element PASSED [ 44%]
tests/test_focus.py::test_never_raises_when_the_automation_call_fails PASSED [ 55%]
tests/test_focus.py::test_silent_for_a_dead_window_handle PASSED         [ 66%]
tests/test_focus.py::test_silent_when_the_window_has_no_process PASSED   [ 77%]
tests/test_focus.py::test_the_hwnd_guard_holds_even_if_the_process_lookup_succeeds FAILED [ 88%]
tests/test_focus.py::test_against_a_real_window_when_the_os_permits_foreground PASSED [100%]

================================== FAILURES ===================================
________ test_the_hwnd_guard_holds_even_if_the_process_lookup_succeeds ________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x00000208FCEAED80>

    def test_the_hwnd_guard_holds_even_if_the_process_lookup_succeeds(monkeypatch):
        ...
        monkeypatch.setattr(focus_module, "_process_id_for", lambda hwnd: TARGET_PID)
        monkeypatch.setattr(
            focus_module,
            "_automation",
            lambda: _FakeAutomation(_FakeElement(TARGET_PID, "1001")),
        )
>       assert read_focused_automation_id(0) == ""
E       AssertionError: assert '1001' == ''
E
E         + 1001

tests\test_focus.py:126: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_focus.py::test_the_hwnd_guard_holds_even_if_the_process_lookup_succeeds
========================= 1 failed, 8 passed in 0.97s =========================
```

Mutation 3 is now verified. `ghostcursor/perception/focus.py` also carries
a comment above the guard explaining it is kept deliberately despite being
redundant today, and naming this test as the proof.

## Mutation 4 failure output (verbatim)

```
tests/test_focus.py::test_never_raises_when_the_automation_call_fails FAILED

    def test_never_raises_when_the_automation_call_fails(wired):
        """The caller is the perception worker, whose product is the walk. Focus
        is a nicety and must never cost an observation."""
        wired(OSError("UIA exploded"))
>       assert read_focused_automation_id(TARGET_HWND) == ""
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_focus.py:94:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <tests.test_focus._FakeAutomation object at 0x00000292FF56AA50>

    def GetFocusedElement(self):
        if isinstance(self._element, Exception):
>           raise self._element
E           OSError: UIA exploded

tests\test_focus.py:49: OSError
=========================== short test summary info ===========================
FAILED tests/test_focus.py::test_never_raises_when_the_automation_call_fails
========================= 1 failed, 7 passed in 0.95s =========================
```

## Summary

4 of 4 mutations now verified against deterministic tests. Mutation 3 (the
`hwnd <= 0` guard) was initially unexercised by `test_silent_for_a_dead_window_handle`,
because `_process_id_for` independently absorbs a bad handle for the two
values (0, -1) that test uses — a coincidental overlap, not a property. A
purpose-built test, `test_the_hwnd_guard_holds_even_if_the_process_lookup_succeeds`,
now isolates the guard by making `_process_id_for` answer for a bogus
handle, matching D030's precedent of keeping a redundant guard and giving
it its own test rather than deleting it or leaving its contribution
unproven.
