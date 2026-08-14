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
