"""Phase B feasibility: it must measure whether a control can be driven
without ever driving it, and must never report a weaker finding as a stronger
one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ghostcursor.devtools import uia_feasibility
from ghostcursor.devtools.uia_feasibility import (
    ObservedTarget,
    decide_feasibility,
    probe_stability,
    verdict_record,
)


def _target(**overrides) -> ObservedTarget:
    values = {
        "automation_id": "",
        "bbox": (10, 20, 30, 40),
        "control_type": "Button",
        "legacy_default_action": None,
        "match_count": 1,
        "name": "New sheet",
        "native_window_handle": None,
        "normalised_name": "New sheet",
        "patterns": {"Invoke": True, "LegacyIAccessible": True},
        "runtime_id": (7, 1234, 5),
    }
    values.update(overrides)
    return ObservedTarget(**values)


# --- backend ranking -------------------------------------------------------


def test_a_true_pattern_outranks_legacy_when_both_are_available():
    """Reporting LegacyIAccessible where Invoke exists would silently lower
    the trust of an action that deserved the stronger class."""

    assert _target().preferred_backend == "Invoke"


def test_legacy_is_reported_when_it_is_genuinely_the_only_option():
    assert (
        _target(patterns={"LegacyIAccessible": True}).preferred_backend
        == "LegacyIAccessible"
    )


def test_a_control_with_no_reviewed_pattern_has_no_backend():
    assert _target(patterns={}).preferred_backend is None


def test_an_unreviewed_pattern_does_not_become_a_backend():
    assert _target(patterns={"ExpandCollapse": True}).preferred_backend is None


# --- stability -------------------------------------------------------------


def test_an_unchanging_control_is_measured_stable():
    result = probe_stability(_target, cycles=5, sleep=lambda _s: None)

    assert result.resolved_cycles == 5
    assert result.observations == 10
    assert result.dwell_intervals == 5
    assert result.cycles_with_identity_change == 0
    assert result.runtime_id_stable is True
    assert result.semantic_identity_stable is True


def test_a_cycle_is_a_pair_not_a_sample_with_a_gap_after_it():
    """Finding: an earlier loop resolved once per iteration and slept between
    iterations, giving N samples across N-1 intervals. The identity claim
    rests on what one cue's dwell does, so a cycle has to contain the dwell."""

    slept: list[float] = []
    result = probe_stability(_target, cycles=3, dwell_s=0.65, sleep=slept.append)

    assert result.cycles == 3
    assert result.observations == 6
    assert slept == [0.65, 0.65, 0.65]


def test_a_changing_runtime_id_disqualifies_it_but_leaves_semantics_intact():
    """The measured VS Code case: the control is there every time, but the
    backend's identity for it moves."""

    ids = iter([(7, 1, n) for n in range(10)])
    result = probe_stability(
        lambda: _target(runtime_id=next(ids)), cycles=5, sleep=lambda _s: None
    )

    assert result.runtime_id_stable is False
    assert result.semantic_identity_stable is True
    assert len(result.distinct_runtime_ids) == 10
    # Measured directly, not inferred: the id moved inside every dwell.
    assert result.cycles_with_identity_change == 5


def test_one_failed_cycle_disqualifies_stability_even_if_every_other_agreed():
    """100/100 means 100 of 100.

    A cycle that could not resolve is not a missing sample -- it is the
    control being absent at the moment the action would have fired.
    """

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("selector matched nothing")
        return _target()

    result = probe_stability(flaky, cycles=5, sleep=lambda _s: None)

    assert result.resolved_cycles == 4
    assert result.fully_resolved is False
    assert result.runtime_id_stable is False
    assert result.semantic_identity_stable is False
    assert len(result.faults) == 1
    assert "cycle 1 before" in result.faults[0]


def test_an_unreadable_runtime_id_is_not_a_stable_runtime_id():
    """Identity that could not be read is not identity (D069)."""

    result = probe_stability(
        lambda: _target(runtime_id=None), cycles=4, sleep=lambda _s: None
    )

    assert result.resolved_cycles == 4
    assert result.runtime_id_stable is False
    assert result.semantic_identity_stable is True


def test_a_selector_that_starts_matching_two_controls_is_not_semantically_stable():
    counts = iter([1, 1, 1, 2, 1, 1, 1, 1])
    result = probe_stability(
        lambda: _target(match_count=next(counts)), cycles=4, sleep=lambda _s: None
    )

    assert result.semantic_identity_stable is False
    assert result.distinct_match_counts == (1, 2)


def test_the_dwell_inside_each_cycle_is_the_cue_budget(monkeypatch):
    """Ordered-sequence check on an injected clock (D026): the gap the claim
    covers must be the gap the real cue imposes."""

    slept: list[float] = []
    probe_stability(_target, cycles=4, dwell_s=0.65, sleep=slept.append)

    assert slept == [0.65, 0.65, 0.65, 0.65]


def test_a_zero_cycle_probe_proves_nothing():
    result = probe_stability(_target, cycles=0, sleep=lambda _s: None)

    assert result.fully_resolved is False
    assert result.runtime_id_stable is False


# --- verdict ---------------------------------------------------------------


def test_a_stable_invokable_control_is_usable_with_runtime_id_required():
    stability = probe_stability(_target, cycles=3, sleep=lambda _s: None)

    verdict = decide_feasibility(_target(), stability)

    assert verdict.usable is True
    assert verdict.backend == "Invoke"
    assert verdict.identity_mode == "runtime_id_required"


def test_an_unstable_runtime_id_demotes_identity_rather_than_refusing():
    ids = iter([(7, 1, n) for n in range(6)])
    stability = probe_stability(
        lambda: _target(runtime_id=next(ids)), cycles=3, sleep=lambda _s: None
    )

    verdict = decide_feasibility(_target(), stability)

    assert verdict.usable is True
    assert verdict.identity_mode == "semantic_exactly_one"
    assert any("evidence-only" in reason for reason in verdict.reasons)


def test_no_stable_identity_of_either_kind_refuses():
    names = iter(["New sheet", "Insert Worksheet"] * 3)
    stability = probe_stability(
        lambda: _target(runtime_id=None, normalised_name=next(names)),
        cycles=3,
        sleep=lambda _s: None,
    )

    verdict = decide_feasibility(_target(), stability)

    assert verdict.usable is False
    assert verdict.identity_mode == "none"


def test_a_control_with_no_pattern_is_refused_however_stable_it_is():
    stability = probe_stability(_target, cycles=3, sleep=lambda _s: None)

    verdict = decide_feasibility(_target(patterns={}), stability)

    assert verdict.usable is False
    assert any("no reviewed UIA pattern" in reason for reason in verdict.reasons)


def test_a_positional_automation_id_is_refused_as_identity():
    stability = probe_stability(_target, cycles=3, sleep=lambda _s: None)

    verdict = decide_feasibility(_target(automation_id="list_id_2_3"), stability)

    assert verdict.usable is False
    assert any("positional" in reason for reason in verdict.reasons)


def test_an_ambiguous_selector_is_refused_rather_than_narrowed_for_the_operator():
    stability = probe_stability(_target, cycles=3, sleep=lambda _s: None)

    verdict = decide_feasibility(_target(match_count=2), stability)

    assert verdict.usable is False
    assert any("not exactly one" in reason for reason in verdict.reasons)


def test_a_legacy_only_control_is_usable_but_says_what_is_weaker_about_it():
    stability = probe_stability(_target, cycles=3, sleep=lambda _s: None)

    verdict = decide_feasibility(
        _target(patterns={"LegacyIAccessible": True}), stability
    )

    assert verdict.usable is True
    assert verdict.backend == "LegacyIAccessible"
    assert any("weaker" in reason for reason in verdict.reasons)
    assert any("signed permission" in reason for reason in verdict.reasons)


def test_the_record_carries_the_measurement_beside_every_claim():
    """D034: a number in evidence names where it came from."""

    stability = probe_stability(_target, cycles=3, sleep=lambda _s: None)
    record = verdict_record(
        "excel", _target(), stability, decide_feasibility(_target(), stability)
    )

    assert record["cycles"] == 3
    assert record["resolved_cycles"] == 3
    assert record["observations"] == 6
    assert record["dwell_intervals"] == 3
    assert record["runtime_id_stable"] is True
    assert record["patterns"] == {"Invoke": True, "LegacyIAccessible": True}
    assert record["type"] == "uia_feasibility"


# --- the read-only guarantee ----------------------------------------------


#: Calling any of these performs an action.  Reading
#: ``LegacyIAccessible.DefaultAction`` is a property read and stays allowed;
#: ``DoDefaultAction`` is the effect and does not.
_ACTION_CALLS = {
    "Invoke",
    "DoDefaultAction",
    "Select",
    "AddToSelection",
    "RemoveFromSelection",
    "Toggle",
    "SetValue",
    "SetFocus",
    "Expand",
    "Collapse",
    "Scroll",
    "ScrollIntoView",
}


def _action_calls_in(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in _ACTION_CALLS:
                found.add(name)
    return found


def test_the_feasibility_probe_calls_nothing_that_acts():
    source = Path(uia_feasibility.__file__).read_text(encoding="utf-8")

    assert _action_calls_in(ast.parse(source)) == set()


@pytest.mark.parametrize(
    "snippet",
    [
        "element.Invoke()",
        "pattern.DoDefaultAction()",
        "control.Toggle()",
        "box.SetValue('x')",
    ],
)
def test_the_action_scan_catches_a_planted_call(snippet):
    """Non-vacuity: a scan that cannot fail proves nothing about the file it
    passed."""

    assert _action_calls_in(ast.parse(snippet))


def test_reading_the_default_action_name_is_not_treated_as_performing_it():
    assert _action_calls_in(ast.parse("name = pattern.CurrentDefaultAction")) == set()
