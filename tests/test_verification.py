import pytest
from unittest import mock

from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.schema import VerificationKind, VerificationRule
from ghostcursor.reasoning.verification import Snapshot, verify, _sort_elements

A = Element("Export", "Button", "1001", (10, 10, 110, 40))
B = Element("Save", "Button", "1002", (10, 50, 110, 80))


def snap(title="App", elements=(A,), focus=""):
    return Snapshot(title=title, elements=tuple(elements), focused_automation_id=focus)


def test_element_appears_detects_a_new_element():
    rule = VerificationRule(
        kind=VerificationKind.ELEMENT_APPEARS,
        args={"target_descriptor": {"name": "Save"}},
    )
    assert verify(rule, snap(elements=(A,)), snap(elements=(A, B))) is True


def test_element_appears_is_false_when_nothing_changed():
    rule = VerificationRule(
        kind=VerificationKind.ELEMENT_APPEARS,
        args={"target_descriptor": {"name": "Save"}},
    )
    assert verify(rule, snap(), snap()) is False


def test_element_disappears():
    rule = VerificationRule(
        kind=VerificationKind.ELEMENT_DISAPPEARS,
        args={"target_descriptor": {"automation_id": "1001"}},
    )
    assert verify(rule, snap(elements=(A, B)), snap(elements=(B,))) is True


def test_window_title_matches():
    rule = VerificationRule(
        kind=VerificationKind.WINDOW_TITLE_MATCHES, args={"pattern": r".*Saved.*"}
    )
    assert verify(rule, snap(title="App"), snap(title="App - Saved")) is True
    assert verify(rule, snap(title="App"), snap(title="App")) is False


def test_focus_moves_to_passes_when_focus_lands_on_the_named_control():
    rule = VerificationRule(
        kind=VerificationKind.FOCUS_MOVES_TO, args={"automation_id": "1004"}
    )
    before = Snapshot(title="t", elements=(), focused_automation_id="1001")
    after = Snapshot(title="t", elements=(), focused_automation_id="1004")
    assert verify(rule, before, after) is True


def test_focus_moves_to_fails_when_focus_did_not_move():
    rule = VerificationRule(
        kind=VerificationKind.FOCUS_MOVES_TO, args={"automation_id": "1004"}
    )
    same = Snapshot(title="t", elements=(), focused_automation_id="1004")
    assert verify(rule, same, same) is False, (
        "focus already there is not focus MOVING there -- a step would "
        "self-satisfy before the user did anything"
    )


def test_focus_moves_to_fails_when_focus_landed_elsewhere():
    rule = VerificationRule(
        kind=VerificationKind.FOCUS_MOVES_TO, args={"automation_id": "1004"}
    )
    before = Snapshot(title="t", elements=(), focused_automation_id="1001")
    after = Snapshot(title="t", elements=(), focused_automation_id="1002")
    assert verify(rule, before, after) is False


def test_focus_moves_to_fails_when_focus_is_unknown():
    """'' means focus could not be named. Treating it as a match would let a
    step pass on no evidence."""
    rule = VerificationRule(
        kind=VerificationKind.FOCUS_MOVES_TO, args={"automation_id": ""}
    )
    before = Snapshot(title="t", elements=(), focused_automation_id="1001")
    after = Snapshot(title="t", elements=(), focused_automation_id="")
    assert verify(rule, before, after) is False


def test_property_changes():
    changed = Element("Exported", "Button", "1001", (10, 10, 110, 40))
    rule = VerificationRule(
        kind=VerificationKind.PROPERTY_CHANGES,
        args={"target_descriptor": {"automation_id": "1001"}, "property": "name"},
    )
    assert verify(rule, snap(elements=(A,)), snap(elements=(changed,))) is True
    assert verify(rule, snap(elements=(A,)), snap(elements=(A,))) is False


def test_any_meaningful_change():
    rule = VerificationRule(
        kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
    )
    assert verify(rule, snap(elements=(A,)), snap(elements=(A, B))) is True
    assert verify(rule, snap(elements=(A,)), snap(elements=(A,))) is False


def test_any_meaningful_change_ignores_pure_movement():
    # A window being dragged is not the user completing a step.
    moved = Element("Export", "Button", "1001", (999, 999, 1099, 1029))
    rule = VerificationRule(
        kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
    )
    assert verify(rule, snap(elements=(A,)), snap(elements=(moved,))) is False


def test_user_confirms_is_never_satisfied_by_observation():
    # It is resolved by the user pressing a key, not by inspecting the screen.
    # This test uses a before/after that WOULD satisfy ELEMENT_APPEARS, proving
    # that USER_CONFIRMS returns False even when other conditions are met.
    # Deleting the explicit USER_CONFIRMS branch would cause an unhandled-kind
    # ValueError to be raised, which is what makes this branch load-bearing.
    rule = VerificationRule(kind=VerificationKind.USER_CONFIRMS)
    assert verify(rule, snap(elements=(A,)), snap(elements=(A, B))) is False


def test_snapshot_elements_order_independence():
    # UIA tree walks have no ordering guarantee. Snapshots with the same
    # elements in different orders must compare equal (value equality, not
    # reference). This matters because the next task detects "user did
    # something unexpected" with after != before on Snapshots.
    elements_order1 = (A, B)
    elements_order2 = (B, A)

    snap1 = Snapshot(title="App", elements=_sort_elements(elements_order1))
    snap2 = Snapshot(title="App", elements=_sort_elements(elements_order2))

    assert snap1 == snap2


def test_any_meaningful_change_with_reordered_elements():
    # Reordering the same elements is not meaningful change; it's a side effect
    # of how UIA enumerates the tree. This test ensures _sort_elements makes
    # Snapshot equality robust to UIA enumeration order.
    moved_to_back = (B, A)  # Same elements, different order
    rule = VerificationRule(
        kind=VerificationKind.ANY_MEANINGFUL_CHANGE, args={"scope": {}}
    )
    assert verify(rule, snap(elements=(A, B)), snap(elements=moved_to_back)) is False


def test_unhandled_verification_kind_raises():
    # Unhandled kinds must raise loudly, not silently return False. This
    # prevents a tour mysteriously stalling with no error hint when a
    # new verification kind is added but not implemented.
    rule = VerificationRule(kind=VerificationKind.ELEMENT_APPEARS, args={})
    # Monkeypatch the kind to an unsupported sentinel value
    with mock.patch.object(rule, "kind", "unsupported_kind"):
        with pytest.raises(ValueError, match="unhandled verification kind"):
            verify(rule, snap(), snap())
