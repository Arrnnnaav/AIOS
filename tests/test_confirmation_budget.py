from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from ghostcursor.devtools import confirmation_budget


def _child_record(index: int, env) -> dict:
    return {
        "verified": True,
        "failure": None,
        "operation": "powerpoint.new_slide_uia",
        "executable_version": "16.0.test",
        "selector": {"sha256": "a" * 64},
        "target_ref": "window-real-equality",
        "target_scope": env["GHOSTCURSOR_CAMPAIGN_SCOPE"],
        "confirmation_timing": {
            "confirmation_round_trip_ms": 100.0 + index,
            "confirmation_to_request_write_ms": 2.0 + index,
        },
    }


def _fake_launch(seen, mutate=None, fail_at=None):
    def launch(command, **kwargs):
        index = len(seen) + 1
        seen.append((tuple(command), kwargs))
        output = Path(command[command.index("--json") + 1])
        record = _child_record(index, kwargs["env"])
        if mutate is not None:
            mutate(record, index, kwargs)
        output.write_text(json.dumps(record), encoding="utf-8")
        return SimpleNamespace(returncode=1 if index == fail_at else 0)

    return launch


def test_every_sample_is_a_fresh_child_but_one_campaign_scope():
    seen = []
    record = confirmation_budget.collect(
        samples=3,
        frame_budget_ms=2,
        traversal_ms=300,
        settle_ms=250,
        launch=_fake_launch(seen),
        executable="python-under-test",
        environment={"PATH": "test"},
    )

    assert record["samples_completed"] == 3
    assert record["failure"] is None
    assert len(seen) == 3
    assert len({call[0][-1] for call in seen}) == 3
    assert {call[1]["env"]["GHOSTCURSOR_CAMPAIGN_SCOPE"] for call in seen} == {
        record["target_scope"]
    }
    assert len({call[1]["env"]["GHOSTCURSOR_CAMPAIGN_SALT"] for call in seen}) == 1
    assert all("ghostcursor.devtools.act_live_node" in call[0] for call in seen)
    assert all(call[1]["timeout"] == 60 for call in seen)


def test_the_first_failed_effect_is_retained_and_later_samples_do_not_run():
    seen = []
    record = confirmation_budget.collect(
        samples=4,
        frame_budget_ms=2,
        traversal_ms=300,
        settle_ms=250,
        launch=_fake_launch(seen, fail_at=2),
        environment={},
    )

    assert len(seen) == 2
    assert record["samples_completed"] == 1
    assert record["failure"] == {
        "sample": 2,
        "returncode": 1,
        "record_present": True,
        "failure_class": None,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda record, *_: record.update(verified=False),
        lambda record, *_: record.update(failure="NodeRefused: no"),
        lambda record, *_: record["confirmation_timing"].update(
            confirmation_round_trip_ms=True
        ),
        lambda record, *_: record["confirmation_timing"].pop(
            "confirmation_to_request_write_ms"
        ),
        lambda record, *_: record.update(operation="other.operation"),
        lambda record, *_: record["selector"].update(sha256=""),
    ],
)
def test_an_untrustworthy_child_record_stops_the_measurement(mutation):
    record = confirmation_budget.collect(
        samples=2,
        frame_budget_ms=2,
        traversal_ms=300,
        settle_ms=250,
        launch=_fake_launch([], mutate=mutation),
        environment={},
    )

    assert record["samples_completed"] == 0
    assert record["failure"]["sample"] == 1


def test_target_or_applicability_drift_refuses_the_whole_record():
    seen = []

    def drift(record, index, _kwargs):
        if index == 2:
            record["target_ref"] = "window-other"

    record = confirmation_budget.collect(
        samples=3,
        frame_budget_ms=2,
        traversal_ms=300,
        settle_ms=250,
        launch=_fake_launch(seen, mutate=drift),
        environment={},
    )

    assert record["samples_completed"] == 2
    assert record["failure"]["failure_class"] == "applicability_drifted"
    assert len(seen) == 2


@pytest.mark.parametrize(
    "failure",
    [OSError("cannot launch"), subprocess.TimeoutExpired(["child"], 60)],
)
def test_launch_failure_or_timeout_stops_later_samples(failure):
    calls = []

    def launch(*_args, **_kwargs):
        calls.append(True)
        raise failure

    record = confirmation_budget.collect(
        samples=3,
        frame_budget_ms=2,
        traversal_ms=300,
        settle_ms=250,
        launch=launch,
        environment={},
    )

    assert calls == [True]
    assert record["samples_completed"] == 0
    assert record["failure"]["sample"] == 1
    assert record["failure"]["failure_class"] == type(failure).__name__


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2"])
def test_counts_and_budgets_require_exact_positive_integers(value):
    with pytest.raises(confirmation_budget.MeasurementRefused):
        confirmation_budget.collect(
            samples=value,
            frame_budget_ms=2,
            traversal_ms=300,
            settle_ms=250,
            launch=_fake_launch([]),
            environment={},
        )


def test_main_refuses_effects_without_explicit_acknowledgement(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        confirmation_budget,
        "collect",
        lambda **_kwargs: called.append(True),
    )

    with pytest.raises(SystemExit, match="acknowledge-live-effects"):
        confirmation_budget.main(
            ["--frame-budget-ms", "2", "--out", str(tmp_path / "record.json")]
        )
    assert called == []


def test_main_never_overwrites_a_record(tmp_path):
    output = tmp_path / "record.json"
    output.write_text("owned", encoding="utf-8")

    with pytest.raises(SystemExit, match="already exists"):
        confirmation_budget.main(
            [
                "--frame-budget-ms",
                "2",
                "--out",
                str(output),
                "--acknowledge-live-effects",
            ]
        )
