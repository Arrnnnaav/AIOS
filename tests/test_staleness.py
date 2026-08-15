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
    now["t"] = 12.0  # time passes with no observation: run is broken
    ladder.observed()
    assert ladder.freshness() is Freshness.HIDDEN


def test_age_reports_time_since_the_last_observation():
    now = {"t": 10.0}
    ladder = _ladder(now)
    ladder.observed()
    now["t"] = 12.5
    assert ladder.age() == 2.5


# --- the silent freeze: observations flowing, nobody reading the verdict ----


def _watched_ladder(now):
    """A ladder whose warnings are captured instead of printed."""
    warnings = []
    ladder = StalenessLadder(clock=lambda: now["t"], warn=warnings.append)
    return ladder, warnings


def test_a_driver_that_never_reads_the_display_state_is_reported():
    """The failure mode with no other symptom.

    A driver that never calls `renderer.settle()` never asks the ladder what
    to draw. Nothing errors: the hint simply stays exactly as it was drawn,
    never dimming and never hiding, while perception hums along. That is the
    shape this project has been bitten by three times, and it is invisible
    precisely because everything looks healthy.
    """
    now = {"t": 100.0}
    ladder, warnings = _watched_ladder(now)

    for _ in range(200):  # 50s of ticks at 4/sec, and nobody ever asks
        now["t"] += 0.25
        ladder.observed()

    assert warnings, (
        "observations flowed for 50s with the display state never read once, "
        "and the ladder said nothing — the overlay would be frozen at "
        "whatever it last drew with no signal at all"
    )
    assert len(warnings) == 1, (
        f"the warning repeated {len(warnings)} times; it must report once, "
        "not once per tick"
    )
    assert "settle" in warnings[0], (
        f"the warning does not name what the driver failed to call: {warnings[0]}"
    )


def test_a_driver_that_reads_every_tick_is_never_reported():
    """The other side of the guard.

    A check that warned regardless would train everyone to ignore it, and
    would fire on every healthy run of the real tour.
    """
    now = {"t": 100.0}
    ladder, warnings = _watched_ladder(now)

    for _ in range(200):
        now["t"] += 0.25
        ladder.observed()
        ladder.freshness()  # what renderer.settle() does, once per tick

    assert warnings == [], f"a correctly-driven ladder warned anyway: {warnings}"


def test_the_report_waits_longer_than_a_hint_takes_to_hide():
    """It must not fire on an ordinary gap.

    The verdict is legitimately unread for short stretches — the tour polls
    ESC and skips ticks before the first observation lands. Warning at the
    hide threshold would make it noise.
    """
    now = {"t": 100.0}
    ladder, warnings = _watched_ladder(now)

    ladder.observed()
    now["t"] += ladder.hide_after_s + 0.5
    ladder.observed()

    assert warnings == [], (
        "the ladder warned about a gap barely longer than hide_after_s: "
        f"{warnings}"
    )
