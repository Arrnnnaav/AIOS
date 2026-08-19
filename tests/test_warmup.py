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

    seen = [warm.allows_tier2(1001)]  # t=0.0, opens here
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

    warm.allows_tier2(splash)  # t=0.0, splash opens
    clock.advance(5.0)
    assert warm.allows_tier2(splash) is True, "splash's own budget expired"

    seen = [warm.allows_tier2(real)]  # t=5.0, real window: fresh budget
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
