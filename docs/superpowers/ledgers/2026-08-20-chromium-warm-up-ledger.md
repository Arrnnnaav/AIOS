# Mutation ledger — Task 1: `WarmUp` policy object

Plan: `.superpowers/sdd/2026-08-20-chromium-warm-up/task-1-brief.md`
Branch: `chromium-warm-up`
Files: `ghostcursor/perception/warmup.py`, `tests/test_warmup.py`
Baseline (all 8 tests passing, no mutation applied): `220d849`

Per D018, each mutation below was applied to `ghostcursor/perception/warmup.py`
one at a time, verified to fail `python -m pytest tests/test_warmup.py -v`,
then reverted with `git checkout -- ghostcursor/perception/warmup.py` before
the next mutation.

## Results

| # | Mutation | Must fail | Actually failed | Result |
|---|---|---|---|---|
| 1 | `allows_tier2` returns `True` unconditionally (first line) | `test_first_sight_of_a_handle_suppresses_tier2` | `test_first_sight_of_a_handle_suppresses_tier2` + 5 others (6 of 8 total) | PASS |
| 2 | `allows_tier2` returns `False` once opened, never expiring | `test_suppressed_for_the_whole_budget_then_allowed` | `test_suppressed_for_the_whole_budget_then_allowed` + `test_a_splash_window_does_not_consume_the_real_windows_budget` | PASS |
| 3 | `note_grounded` becomes a no-op (`pass`) | `test_grounding_closes_warm_up_permanently` | `test_grounding_closes_warm_up_permanently` + `test_handles_are_independent` | PASS |
| 4 | Key by constant `1` instead of `hwnd` throughout | `test_a_splash_window_does_not_consume_the_real_windows_budget` **and** `test_handles_are_independent` | both of those, plus `test_opens_counts_distinct_handles_only` | PASS |

Mutation 4 is the one that matters: it is exactly "keyed by title, not by
handle," the measured Discord defect (`Discord Updater` is a distinct HWND
that shares the title regex with the real Discord window and would otherwise
absorb the whole warm-up budget). It failed both required tests, so the
central claim of this design — that keying by HWND, not by title, is what
prevents the splash window from starving the real window's budget — is
exercised by the suite, not merely asserted in the docstring.

### Mutation 4 failure output (verbatim)

```
tests/test_warmup.py::test_a_splash_window_does_not_consume_the_real_windows_budget FAILED [ 50%]
tests/test_warmup.py::test_handles_are_independent FAILED                [ 62%]
tests/test_warmup.py::test_opens_counts_distinct_handles_only FAILED     [100%]

================================== FAILURES ===================================
________ test_a_splash_window_does_not_consume_the_real_windows_budget ________

    ...
        assert warm.allows_tier2(splash) is True, "splash's own budget expired"

        seen = [warm.allows_tier2(real)]  # t=5.0, real window: fresh budget
        clock.advance(1.0)
        seen.append(warm.allows_tier2(real))  # t=6.0, still inside its own budget
        clock.advance(1.5)
        seen.append(warm.allows_tier2(real))  # t=7.5, expired

>       assert seen == [False, False, True]
E       AssertionError: assert [True, True, True] == [False, False, True]
E
E         At index 0 diff: True != False

tests\test_warmup.py:74: AssertionError
________________________ test_handles_are_independent _________________________

    def test_handles_are_independent():
        warm = WarmUp(budget_s=2.0, clock=FakeClock())
        warm.allows_tier2(1001)
        warm.note_grounded(1001)
        assert warm.allows_tier2(1001) is True
>       assert warm.allows_tier2(2002) is False, "closing one window closed another"
E       AssertionError: closing one window closed another
E       assert True is False
E        +  where True = allows_tier2(2002)
E        +    where allows_tier2 = <ghostcursor.perception.warmup.WarmUp object at 0x0000012A5D44B7A0>.allows_tier2

tests\test_warmup.py:82: AssertionError
___________________ test_opens_counts_distinct_handles_only ___________________

    ...
        warm.allows_tier2(2002)
>       assert warm.opens == 2
E       assert 1 == 2

tests\test_warmup.py:108: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_warmup.py::test_a_splash_window_does_not_consume_the_real_windows_budget
FAILED tests/test_warmup.py::test_handles_are_independent - AssertionError: c...
FAILED tests/test_warmup.py::test_opens_counts_distinct_handles_only - assert...
========================= 3 failed, 5 passed in 0.36s =========================
```

After reverting mutation 4, `python -m pytest tests/test_warmup.py -v` again
reports 8 passed, confirming the working tree was restored cleanly to the
committed baseline before this ledger was written.

Full command output for all four mutations and the clean baseline is in
`.superpowers/sdd/2026-08-20-chromium-warm-up/task-1-report.md`.

# Mutation ledger — Task 3: wiring `WarmUp` into `run_tour`

Plan: `.superpowers/sdd/2026-08-20-chromium-warm-up/task-3-brief.md`
Branch: `chromium-warm-up`
Files: `ghostcursor/run.py`, `tests/test_warmup_tour.py`
Baseline (all 5 tests passing, no mutation applied): `414837c`

Per D018, each mutation below was applied to `ghostcursor/run.py` alone, one
at a time, verified to fail the named test under
`python -m pytest tests/test_warmup_tour.py::<name> -q`, then reverted from a
saved copy of the committed file before the next mutation. After all four,
`git status --porcelain ghostcursor/run.py` was empty and
`python -m pytest tests/test_warmup_tour.py -q` again reported 5 passed,
confirming the working tree was restored cleanly to the committed baseline.

## Results

| # | Mutation | Must fail | Actually failed | Result |
|---|---|---|---|---|
| 1 | Delete the `if not warmup.allows_tier2(...): return None` guard (leave `service.request_tier2(i)` unconditional) | `test_a_cold_window_that_grounds_inside_the_budget_never_asks_for_tier2` | that test — `tier2_requests` became `[0, 0]` instead of `[]` | PASS |
| 2 | Make the guard permanent — `if True: return None` in its place | `test_a_window_that_never_grounds_asks_once_the_budget_expires` | that test — `tier2_requests` stayed `[]` even after the 2.0s budget expired | PASS |
| 3 | Delete the `warmup.note_grounded(...)` call on the grounding-success path | `test_warm_up_does_not_reopen_after_a_successful_grounding` | that test — a later grounding failure for the same hwnd got a second warm-up allowance instead of escalating immediately | PASS |
| 4 | Pass a constant instead of the handle: `warmup.allows_tier2(1)` | `test_a_splash_window_does_not_spend_the_real_windows_budget` | that test — the splash's already-open-and-expired warm-up (keyed to the constant `1`) was reused for the real window, suppressing its tier-2 request | PASS |

Mutation 4 is the load-bearing one, per the brief: it reproduces the measured
Discord defect where a splash window (`Discord Updater`) and the real window
share a title regex but are different HWNDs. Keying `allows_tier2` on
anything other than the real per-window handle collapses the two windows'
warm-up state into one entry, so the splash's long-expired budget gets
credited to the real window and its first-sight allowance is silently lost.
It failed exactly the test the brief names as required, confirming that
HWND-keying (not a constant, and not the title regex) is what this task's
wiring actually depends on — not merely asserted in a comment.

### Mutation 4 failure output (verbatim)

```
tests/test_warmup_tour.py::test_a_splash_window_does_not_spend_the_real_windows_budget FAILED

    def test_a_splash_window_does_not_spend_the_real_windows_budget(warmup_harness):
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

>       assert h.tier2_requests == [], (
            "the splash's expired budget was reused for the real window"
        )
E       AssertionError: the splash's expired budget was reused for the real window
E       assert [0] == []
E
E         Left contains one more item: 0

tests\test_warmup_tour.py:298: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_warmup_tour.py::test_a_splash_window_does_not_spend_the_real_windows_budget
1 failed in 1.13s
```

Full command output for all four mutations is in
`.superpowers/sdd/2026-08-20-chromium-warm-up/task-3-report.md`.
