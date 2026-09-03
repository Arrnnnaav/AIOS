"""A campaign counts three consecutive clean runs, or it counts nothing.

The 3/3 policy is a claim about consecutive independent runs, so the thing
counting them has to be at least as careful as the thing running them. Every
case here is a way a campaign could report a pass it did not observe.

No subprocess is started: the launcher is injected, so these run hermetically.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ghostcursor.devtools.act_campaign import (
    Attempt,
    CampaignError,
    attempt_from,
    read_records,
    run_campaign,
)


def _stdout(*records) -> str:
    return "\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n"


def _result(completed=True, code="completed", nodes=255, published="a" * 64):
    return {
        "code": code,
        "completed": completed,
        "completed_nodes": nodes,
        "detail": "Act plan completed",
        "output_path": "D:/deck.pptx",
        "published_sha256": published,
        "type": "result",
    }


def _launcher(*payloads):
    """Returns a launcher yielding one stdout per attempt, and a log of the
    argv it was given, so 'fresh paths per attempt' can be asserted."""

    calls = []
    remaining = list(payloads)

    def launch(command, capture_output=True, text=True, timeout=None):
        calls.append(list(command))
        payload = remaining.pop(0) if remaining else _stdout(_result())
        return SimpleNamespace(stdout=payload, stderr="", returncode=0)

    launch.calls = calls
    return launch


def _one_window(_class_name):
    return (4242,)


def _run(tmp_path, attempts=3, launch=None, restore=_one_window):
    return run_campaign(
        attempts=attempts,
        build_command=lambda index, store, output: [
            "python",
            "--store-root",
            str(store),
            "--output",
            str(output),
        ],
        workspace=tmp_path,
        window_class="PPTFrameClass",
        restore=restore,
        launch=launch or _launcher(),
        settle_s=0,
    )


# --- three consecutive clean runs -----------------------------------------


def test_three_clean_attempts_make_a_clean_campaign(tmp_path):
    attempts = _run(tmp_path)

    assert len(attempts) == 3
    assert all(a.clean for a in attempts)
    assert [a.index for a in attempts] == [1, 2, 3]


def test_each_attempt_gets_its_own_store_and_output(tmp_path):
    """Reusing either would let one attempt's state decide the next one's
    outcome, and 'three consecutive' would stop meaning three independent
    runs."""

    launch = _launcher()
    _run(tmp_path, launch=launch)

    stores = [c[c.index("--store-root") + 1] for c in launch.calls]
    outputs = [c[c.index("--output") + 1] for c in launch.calls]

    assert len(set(stores)) == 3
    assert len(set(outputs)) == 3


def test_the_runner_chooses_the_paths_not_the_caller(tmp_path):
    """`build_command` is HANDED the paths. If it chose them, 'fresh per
    attempt' would be a habit of the caller rather than a property here."""

    import inspect

    signature = inspect.signature(run_campaign)

    assert "build_command" in signature.parameters
    seen = []
    run_campaign(
        attempts=1,
        build_command=lambda index, store, output: (
            seen.append((store, output)) or ["x"]
        ),
        workspace=tmp_path,
        window_class="C",
        restore=_one_window,
        launch=_launcher(),
        settle_s=0,
    )
    assert seen and seen[0][0] != seen[0][1]


# --- a campaign stops at the first attempt that is not clean --------------


def test_a_failed_attempt_ends_the_campaign(tmp_path):
    """Continuing would produce '3 of 5 passed', which is not what the policy
    asks and reads like a pass rate."""

    launch = _launcher(
        _stdout(_result()),
        _stdout(_result(completed=False, code="verification_failed", nodes=24)),
        _stdout(_result()),
    )

    with pytest.raises(CampaignError, match="was not clean"):
        _run(tmp_path, launch=launch)

    assert len(launch.calls) == 2, "the third attempt must not have started"


def test_a_run_that_verified_but_did_not_publish_is_not_clean(tmp_path):
    """Every node verified and no artifact exists. Counting that as clean
    would mean the campaign passed on a deck nobody can open."""

    launch = _launcher(_stdout(_result(published=None)))

    with pytest.raises(CampaignError, match="published=False"):
        _run(tmp_path, attempts=1, launch=launch)


def test_a_stopped_attempt_is_not_clean(tmp_path):
    launch = _launcher(
        _stdout(_result(completed=False, code="stopped", nodes=44, published=None))
    )

    with pytest.raises(CampaignError, match="stopped"):
        _run(tmp_path, attempts=1, launch=launch)


# --- a probe is never an attempt ------------------------------------------


def test_an_interrupt_probe_record_refuses_the_campaign():
    """Not because a probe is invalid, but because its presence means the
    campaign was configured to interrupt itself — never what a counted
    campaign wants."""

    records = read_records(
        _stdout({"type": "interrupt_probe", "code": "stopped", "completed": False})
    )

    with pytest.raises(CampaignError, match="interrupt_probe"):
        attempt_from(1, records, 1.0)


def test_a_probe_is_refused_even_beside_a_result():
    """The dangerous shape: a run that emitted both. Counting the result and
    ignoring the probe would count an interrupted run as an attempt."""

    records = read_records(
        _stdout(
            {"type": "interrupt_probe", "code": "stopped", "completed": False},
            _result(),
        )
    )

    with pytest.raises(CampaignError, match="interrupt_probe"):
        attempt_from(1, records, 1.0)


# --- an unknown outcome is never counted ----------------------------------


def test_a_run_with_no_result_record_is_refused():
    """An unknown outcome counted as anything at all is how a campaign
    reports a pass it did not observe."""

    with pytest.raises(CampaignError, match="0 result records"):
        attempt_from(1, read_records(_stdout({"type": "staged"})), 1.0)


def test_a_run_with_two_result_records_is_refused():
    with pytest.raises(CampaignError, match="2 result records"):
        attempt_from(1, read_records(_stdout(_result(), _result())), 1.0)


def test_unparseable_output_lines_are_skipped_not_guessed_at():
    records = read_records("not json\n" + _stdout(_result()) + "also not json\n")

    assert len(records) == 1
    assert attempt_from(1, records, 1.0).clean is True


# --- the target has to be there, and visible ------------------------------


def test_a_minimised_window_is_restored_before_each_attempt(tmp_path):
    """Measured: a build refused with 'no window matches pack powerpoint'
    because PowerPoint had minimised itself. Correct behaviour, and a
    terrible campaign failure, because the message names the pack rather
    than the cause."""

    restored = []

    def restore(class_name):
        restored.append(class_name)
        return (4242,)

    _run(tmp_path, restore=restore)

    assert restored == ["PPTFrameClass"] * 3


def test_no_target_window_refuses_before_launching_anything(tmp_path):
    launch = _launcher()

    with pytest.raises(CampaignError, match="found 0"):
        _run(tmp_path, launch=launch, restore=lambda _c: ())

    assert launch.calls == []


def test_two_target_windows_refuse_rather_than_choosing(tmp_path):
    """Choosing between them is never the software's call (D075)."""

    with pytest.raises(CampaignError, match="found 2"):
        _run(tmp_path, restore=lambda _c: (1, 2))


def test_the_target_is_rechecked_before_every_attempt(tmp_path):
    """A window that disappears between attempts must stop the campaign, not
    be assumed from the first check."""

    answers = iter([(4242,), ()])
    launch = _launcher()

    with pytest.raises(CampaignError, match="attempt 2"):
        _run(tmp_path, launch=launch, restore=lambda _c: next(answers))

    assert len(launch.calls) == 1


# --- shape ----------------------------------------------------------------


@pytest.mark.parametrize("attempts", [0, -1, True, 1.5, "3"])
def test_a_malformed_attempt_count_is_refused(tmp_path, attempts):
    with pytest.raises(CampaignError, match="at least one attempt"):
        _run(tmp_path, attempts=attempts)


def test_an_attempt_is_frozen():
    attempt = Attempt(1, True, "completed", 255, "a" * 64, "D:/d.pptx", 1.0)

    with pytest.raises(Exception):
        attempt.completed = False


def test_the_runner_offers_no_parallel_mode():
    """D025 forbids two desktop/UIA sessions at once. A parallel flag would
    be a temptation the runner should not contain."""

    import inspect

    source = inspect.getsource(run_campaign)

    assert "parallel" not in source.lower()
    assert "thread" not in source.lower()
