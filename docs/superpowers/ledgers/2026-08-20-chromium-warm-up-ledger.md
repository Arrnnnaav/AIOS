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
