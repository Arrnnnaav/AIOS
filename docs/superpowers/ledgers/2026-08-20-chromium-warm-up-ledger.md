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

Mutations 5 and 6 were added after review (see
`.superpowers/sdd/2026-08-20-chromium-warm-up/task-3-report.md`, "Fix report"
section) once `test_the_budget_parameter_is_what_warm_up_actually_uses` made
the suite 6 tests; they were verified against that 6-test baseline the same
way, then reverted the same way.

## Results

| # | Mutation | Must fail | Actually failed | Result |
|---|---|---|---|---|
| 1 | Delete the `if not warmup.allows_tier2(...): return None` guard (leave `service.request_tier2(i)` unconditional) | `test_a_cold_window_that_grounds_inside_the_budget_never_asks_for_tier2` | that test — `tier2_requests` became `[0, 0]` instead of `[]` | PASS |
| 2 | Make the guard permanent — `if True: return None` in its place | `test_a_window_that_never_grounds_asks_once_the_budget_expires` | that test — `tier2_requests` stayed `[]` even after the 2.0s budget expired | PASS |
| 3 | Delete the `warmup.note_grounded(...)` call on the grounding-success path | `test_warm_up_does_not_reopen_after_a_successful_grounding` | that test — a later grounding failure for the same hwnd got a second warm-up allowance instead of escalating immediately | PASS |
| 4 | Pass a constant instead of the handle: `warmup.allows_tier2(1)` | `test_a_splash_window_does_not_spend_the_real_windows_budget` | that test — the splash's already-open-and-expired warm-up (keyed to the constant `1`) was reused for the real window, suppressing its tier-2 request | PASS |
| 5 | Hardcode the budget: `WarmUp(budget_s=2.0, clock=clock)` instead of `warmup_budget_s` | `test_the_budget_parameter_is_what_warm_up_actually_uses` (and nothing else) | exactly that test — a 0.5s budget never expired because 2.0s was baked in; the other 5 tests all pass `budget_s=2.0`, indistinguishable from the hardcoded literal, so none of them noticed | PASS |
| 6 | Break the shared clock: `WarmUp(budget_s=warmup_budget_s, clock=time.monotonic)` instead of `clock` | `test_a_window_that_never_grounds_asks_once_the_budget_expires` (reviewer-predicted) | that test, plus `test_the_budget_parameter_is_what_warm_up_actually_uses` (2 of 6) — a real wall clock never advances under the test's `advance()` calls on the fake clock, so the budget appeared never to expire | PASS |

Mutation 5 is the direct answer to Important finding 2: it shows the four
original behavioural tests (all run at `budget_s=2.0`, the same value as
`DEFAULT_WARMUP_BUDGET_S`) cannot tell "the parameter was threaded through"
apart from "2.0 is hardcoded at the call site" — only the new non-default-
budget test can, and does. Mutation 6 is the shared-clock constraint's
evidence, exactly as the reviewer predicted: `test_a_window_that_never_
grounds_asks_once_the_budget_expires` already catches a `WarmUp` built on a
clock other than `run_tour`'s own, with no new test needed for that half.

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

### Mutation 5 failure output (verbatim)

```
================================== FAILURES ===================================
___________ test_the_budget_parameter_is_what_warm_up_actually_uses ___________

    def test_the_budget_parameter_is_what_warm_up_actually_uses(warmup_harness):
        h = warmup_harness(budget_s=0.5, hwnd=1638728)

        h.tick()  # t=0.0  warm-up opens
        h.advance(0.4)
        h.tick()  # t=0.4  inside a 0.5s budget
        inside = list(h.tier2_requests)
        h.advance(0.2)
        h.tick()  # t=0.6  expired
        after = list(h.tier2_requests)

        assert inside == [], "asked before the 0.5s budget expired"
>       assert after, "0.5s budget never expired -- 2.0s is hardcoded at the call site"
E       AssertionError: 0.5s budget never expired -- 2.0s is hardcoded at the call site
E       assert []

tests\test_warmup_tour.py:341: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_warmup_tour.py::test_the_budget_parameter_is_what_warm_up_actually_uses
1 failed, 5 passed in 0.84s
```

### Mutation 6 failure output (verbatim)

```
=========================== short test summary info ===========================
FAILED tests/test_warmup_tour.py::test_a_window_that_never_grounds_asks_once_the_budget_expires
FAILED tests/test_warmup_tour.py::test_the_budget_parameter_is_what_warm_up_actually_uses
2 failed, 4 passed in 0.89s
```

`test_a_window_that_never_grounds_asks_once_the_budget_expires`'s relevant
assertion:

```
        assert inside == [], "asked before the budget expired"
>       assert after, "never asked after the budget expired -- tier 2 is dead"
E       AssertionError: never asked after the budget expired -- tier 2 is dead
E       assert []
```

Full command output for all six mutations is in
`.superpowers/sdd/2026-08-20-chromium-warm-up/task-3-report.md`.

# Mutation ledger — Final review fix wave (2026-08-20)

Plan: whole-branch review fix wave, `.superpowers/sdd/2026-08-20-chromium-warm-up/final-fix-report.md`
Branch: `chromium-warm-up`
Files: `ghostcursor/run.py`, `tests/test_warmup_tour.py`
Baseline (297 passed, no mutation applied): `02f3ae7`

## Real defect fixed

The review found that warm-up suppressed NEW tier-2 requests per window but
never retracted a STANDING one across a WINDOW boundary (only at a step
boundary or on UIA grounding success). `run.py`'s tier-2 request site now
calls `service.cancel_tier2(i)` whenever `warmup.allows_tier2(target_hwnd)`
is false, immediately before returning `None`.

The original `test_a_splash_window_does_not_spend_the_real_windows_budget`
passed identically with and without this fix, because
`_ScriptedService.cancel_tier2` was a no-op and the test only inspected
`tier2_requests` after explicitly clearing it right where the defect would
have shown up. Per D018, `_ScriptedService` was given a `standing: int |
None` attribute that `request_tier2` sets and `cancel_tier2` clears, and the
test now asserts `h.service.standing is None` right after the real window's
first-sight tick — the exact point a standing splash request must have been
retracted.

## Results

| # | Mutation | Must fail | Actually failed | Result |
|---|---|---|---|---|
| 1 | Remove `service.cancel_tier2(i)` from the `not warmup.allows_tier2(...)` branch in `run.py` (leave the `return None` in place) | `test_a_splash_window_does_not_spend_the_real_windows_budget` | that test — `h.service.standing` was `0` (the splash's request) instead of `None` right after the real window's first-sight tick | PASS |

Per D018, the mutation was applied by editing `ghostcursor/run.py` directly,
verified to fail `python -m pytest
tests/test_warmup_tour.py::test_a_splash_window_does_not_spend_the_real_windows_budget
-q`, then reverted with `git checkout -- ghostcursor/run.py` and reverified
clean (`git status --porcelain ghostcursor/run.py` empty, full
`test_warmup_tour.py` back to 6 passed).

### Mutation 1 failure output (verbatim)

```
F                                                                        [100%]
================================== FAILURES ===================================
_________ test_a_splash_window_does_not_spend_the_real_windows_budget _________

warmup_harness = <function warmup_harness.<locals>.factory at 0x000002E72265C540>

    def test_a_splash_window_does_not_spend_the_real_windows_budget(warmup_harness):
        """The measured Discord case, end to end: 'Discord Updater' (hwnd 329088)
        for ~5s, then the real window (hwnd 1638728) whose tree is ready in 0.92s."""
        h = warmup_harness(budget_s=2.0, hwnd=329088)

        h.tick()  # t=0.0  splash seen
        h.advance(5.0)
        h.tick()  # t=5.0  splash budget long expired -- standing request now open
        assert h.service.standing == 0, "splash never got its expected request"
        h.set_hwnd(1638728)  # the real window replaces it
        h.tier2_requests.clear()
        h.tick()  # t=5.0  real window, first sight
>       assert h.service.standing is None, (
            "the splash's standing request was never retracted -- it outlives "
            "the real window's own warm-up and keeps costing capture+OCR"
        )
E       AssertionError: the splash's standing request was never retracted -- it outlives the real window's own warm-up and keeps costing capture+OCR
E       assert 0 is None
E        +  where 0 = <tests.test_warmup_tour._ScriptedService object at 0x000002E723134EC0>.standing
E        +    where <tests.test_warmup_tour._ScriptedService object at 0x000002E723134EC0> = <tests.test_warmup_tour._WarmupHarness object at 0x000002E7231360F0>.service

tests\test_warmup_tour.py:365: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_warmup_tour.py::test_a_splash_window_does_not_spend_the_real_windows_budget
1 failed in 0.83s
```

After reverting, `python -m pytest tests/test_warmup_tour.py -q` again
reported 6 passed, and `python -m pytest tests/
--ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py
--ignore=tests/test_run_threaded.py -q` reported 297 passed, confirming the
working tree was restored cleanly to the committed baseline (`02f3ae7`).

## Mutation — the real-window wiring test (`tests/test_warmup_real_window.py`)

Applied by the controller, not by the test's author, so the check and the code
under it have different provenance (D032).

**Mutation:** `first_matching_hwnd` in `ghostcursor/perception/uia.py` forced to
`return 0`, simulating a regression where the production `hwnd_source` stops
seeing a window that is plainly on screen.

**Result — the whole point of this test, quantified:**

```
FAILED tests/test_warmup_real_window.py::test_a_real_windows_handle_reaches_warmup_and_is_not_the_zero_bypass
1 failed, 297 passed in 18.98s
```

Verbatim failure, at the intended assertion:

```
>               assert observation.target_hwnd != 0, (
E               AssertionError: PerceptionService published target_hwnd=0 for a window
                that is demonstrably on screen -- first_matching_hwnd (the production
                hwnd_source default) is not seeing it, which silently disables warm-up
                for every application
E               assert 0 != 0
E                +  where 0 = Observation(..., target_hwnd=0).target_hwnd
tests\test_warmup_real_window.py:91: AssertionError
```

**297 pre-existing tests pass while warm-up is completely disabled in
production.** That is not a coverage shortfall — it is a suite that would have
certified a broken build as correct, because every one of those tests
constructs `Observation` with the default `target_hwnd = 0` and therefore
exercises `WarmUp`'s deliberate `hwnd <= 0` bypass rather than the real path.
Exactly one test now stands between that regression and a green build.

Reverted; `git diff` clean; the test passes again (1 passed in 0.78s), and it
ran green four consecutive times before the mutation (1.18s, 0.76s, 0.71s,
0.73s), so it is not timing-flaky against a real window.

## Mutation — the tick-loop wiring test (`tests/test_warmup_real_window.py::test_the_tick_loop_suppresses_tier2_through_the_real_wiring`)

First round applied by the controller (D032), who found a real defect in the
test itself, not the code: the suppression assertion anchored its budget
window to `time.monotonic()` captured immediately before the background
thread launched, not to when warm-up actually opened. Between those two
events `run_tour` must construct a `PerceptionService`, start its worker,
complete a real UIA walk, and publish an observation before it ever reaches
its first failed grounding — the moment `warmup.allows_tier2` is first
consulted. That startup cost alone can exceed a short budget, so the window
could read empty because nothing had happened yet, not because anything was
suppressed.

**Mutation applied to `ghostcursor/run.py`:** delete the whole suppression
branch —

```python
target_hwnd = observation.target_hwnd if observation is not None else 0
if not warmup.allows_tier2(target_hwnd):
    # A standing request from a previous window (or from the
    # ticks before this one existed) is a standing COST on the
    # worker; nothing but this ends it, and warm-up means we do
    # not want it. Same argument as the UIA-success path above.
    service.cancel_tier2(i)
    return None
service.request_tier2(i)
```

reduced to

```python
target_hwnd = observation.target_hwnd if observation is not None else 0
service.request_tier2(i)
```

i.e. `service.request_tier2(i)` now fires unconditionally on the very first
failed grounding — warm-up does not exist at all.

**Result against the thread-launch-anchored version (round 1, before the
fix):** `2 passed in 4.30s`. The test proved nothing about warm-up; this was
the false green.

**Fix:** spy `ghostcursor.reasoning.grounding.ground` the same way
`PerceptionService.request_tier2` is spied (module-level monkeypatch,
timestamped with `time.monotonic()`), and anchor the suppression window to
the timestamp of the first call that returned `None` (a failed grounding) —
the real moment `allows_tier2` is first consulted, not thread-launch. Widened
`budget_s`/`total_seconds` from 0.5s/3.0s to 1.5s/5.0s for margin.

**Result against the fixed, event-anchored version (round 2):**

```
FAILED tests/test_warmup_real_window.py::test_the_tick_loop_suppresses_tier2_through_the_real_wiring
1 failed, 7 warnings in 6.19s
```

Verbatim failure, at the suppression assertion (the one the mutation targets):

```
        requested_at = [t for t, _ in requests]

        suppressed_window = [t for t in requested_at if t < budget_expires_at]
>       assert suppressed_window == [], (
            f"tier 2 was requested at t={[t - warmup_opened_at for t in suppressed_window]}s "
            f"relative to warm-up opening, before the {budget_s}s budget "
            "expired -- warm-up did not suppress for a real, "
            "production-sourced window handle"
        )
E       AssertionError: tier 2 was requested at t=[0.0, 0.5, 1.0309999999954016]s relative to warm-up opening, before the 1.5s budget expired -- warm-up did not suppress for a real, production-sourced window handle
E       assert [36512.078, 3...78, 36513.109] == []
E
E         Left contains 3 more items, first extra item: 36512.078
E           Use -v to get more diff

tests\test_warmup_real_window.py:296: AssertionError
```

The first tier-2 request landed at t=0.0s relative to warm-up opening —
i.e. in the very same tick grounding first failed — which is exactly what
"the guard is gone" looks like, and is unambiguous against a 1.5s budget.

Reverted with `git checkout -- ghostcursor/run.py`; `git diff --stat
ghostcursor/run.py` empty, confirming a clean restore. Re-ran green:
`2 passed` for the file, `299 passed` for the fast suite
(`--ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py
--ignore=tests/test_run_threaded.py`).

### 5 consecutive stability runs (event-anchored version, post-fix, run.py restored)

Each run: `python -m pytest
tests/test_warmup_real_window.py::test_the_tick_loop_suppresses_tier2_through_the_real_wiring
-q`, run alone, never alongside another pytest session.

1. `1 passed` — 5.84s
2. `1 passed` — 5.88s
3. `1 passed` — 5.74s
4. `1 passed` — 6.05s
5. `1 passed` — 6.13s

## What this test now proves, and what it does not

Proves, through the real production wiring (`ghostcursor.run.run_tour`, a
real `PerceptionService` with the default `hwnd_source=first_matching_hwnd`,
a real UIA walk against a real `SyntheticApp` window, the real tick loop):

- **Suppression**: no `request_tier2` call lands before the warm-up budget,
  measured from the real event (first failed grounding), expires.
- **Release**: at least one `request_tier2` call lands after that budget
  expires, within the tour's deadline — so the test cannot pass for the
  trivial reason that tier 2 was never going to fire at all.

Does not prove: anything about the OCR read itself (tier-2's `elements_for`,
`engaged`, `exhausted` — covered elsewhere), or behavior across a window
transition (splash-to-real-window; covered by
`test_warmup_tour.py::test_a_splash_window_does_not_spend_the_real_windows_budget`
on the scripted service). Those remain out of scope for this file, whose job
is only the real-handle x real-tick-loop seam.
