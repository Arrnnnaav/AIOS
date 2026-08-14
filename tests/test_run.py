"""Covers findings 2 and 4 from the whole-branch review of run.py:

- finding 2: the grounder wired into a live run_tour must call
  grounding.promote() after a successful grounding, or spec §5's promotion
  mechanism never runs outside the test suite.
- finding 4: ESC/SPACE must be detected on a tap, not just while held, and
  SPACE must only be polled while the current step is actually waiting on a
  user confirmation.
"""

import sqlite3

import pytest

import ghostcursor.run as run_module
from ghostcursor.overlay import window
from ghostcursor.perception import appinfo
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning import grounding
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Recipe,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)
from ghostcursor.run import key_was_pressed, make_grounder, should_poll_space

EN = [Element("Export", "Button", "1001", (10, 10, 110, 40))]

VK_ESCAPE = 0x1B
_CURRENTLY_DOWN = 0x8000
_PRESSED_SINCE_LAST_CALL = 0x0001


def _step(kind=VerificationKind.USER_CONFIRMS, args=None):
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=kind, args=args or {}),
        risk=Risk.NORMAL,
    )


# --- finding 4: key-state predicate against both bits -----------------------


def test_key_was_pressed_true_when_currently_down():
    assert key_was_pressed(VK_ESCAPE, key_state=lambda vk: _CURRENTLY_DOWN) is True


def test_key_was_pressed_true_when_only_tapped_since_last_call():
    # The key is UP right now but was pressed at some point since the last
    # poll. A single tick can exceed a second (three UIA tree walks, each
    # able to block), so this bit is what makes a tapped ESC reliable.
    assert (
        key_was_pressed(VK_ESCAPE, key_state=lambda vk: _PRESSED_SINCE_LAST_CALL)
        is True
    )


def test_key_was_pressed_false_when_neither_bit_set():
    assert key_was_pressed(VK_ESCAPE, key_state=lambda vk: 0x0000) is False


def test_key_was_pressed_forwards_the_right_virtual_key_code():
    seen = []

    def fake_key_state(vk):
        seen.append(vk)
        return 0

    key_was_pressed(VK_ESCAPE, key_state=fake_key_state)
    assert seen == [VK_ESCAPE]


# --- finding 4: SPACE only polled for user_confirms steps -------------------


def test_should_poll_space_true_for_a_user_confirms_step():
    assert should_poll_space(_step(kind=VerificationKind.USER_CONFIRMS)) is True


def test_should_poll_space_false_for_a_non_user_confirms_step():
    # Otherwise a space typed into some other application would silently
    # advance the tour -- inventing progress the user never made.
    step = _step(
        kind=VerificationKind.ELEMENT_APPEARS,
        args={"target_descriptor": {"name": "Save"}},
    )
    assert should_poll_space(step) is False


def test_should_poll_space_false_when_there_is_no_current_step():
    assert should_poll_space(None) is False


# --- finding 2: the live grounder promotes after a successful grounding -----


def test_make_grounder_promotes_after_a_successful_grounding(monkeypatch):
    monkeypatch.setattr(grounding, "iter_elements", lambda title_re: EN)
    step = _step()
    assert step.target_descriptor.confirmed == []

    grounder = make_grounder(".*")
    result = grounder(step, 0)

    assert result is not None
    assert step.target_descriptor.confirmed, (
        "grounding succeeded but promote() never ran -- rung 1 stays "
        "unreachable outside the test suite"
    )
    observation = step.target_descriptor.confirmed[0]
    assert observation.automation_id == "1001"
    # app_version="unknown" is deliberate here: real version detection is
    # spec §9, deferred knowledge-base scope.
    assert observation.app_version == "unknown"


def test_make_grounder_does_not_promote_on_a_failed_grounding(monkeypatch):
    monkeypatch.setattr(grounding, "iter_elements", lambda title_re: [])
    step = _step()

    grounder = make_grounder(".*")
    result = grounder(step, 0)

    assert result is None
    assert step.target_descriptor.confirmed == []


# --- finding 2 (whole-branch review): a store failure degrades, not crashes -


class _RaisingStore:
    """Stands in for a store whose record() hits a locked/full/read-only db."""

    def record(self, step_key, app_id, observation):
        raise sqlite3.OperationalError("database is locked")


def test_make_grounder_survives_a_persist_failure(monkeypatch):
    # Grounding succeeds and promotes in-memory; only the on-disk persist
    # step fails. The grounder must still return the GroundedTarget rather
    # than letting sqlite3.Error propagate out of the tour loop.
    monkeypatch.setattr(grounding, "iter_elements", lambda title_re: EN)
    from ghostcursor.perception.appinfo import AppInfo

    app_info = AppInfo(
        app_id="app.exe", exe_path=r"C:\app.exe", version="1.0", kind="win32"
    )
    step = _step()

    grounder = make_grounder(
        ".*", app_info=app_info, store=_RaisingStore(), recipe_intent="do a thing"
    )
    result = grounder(step, 0)

    assert result is not None
    assert step.target_descriptor.confirmed, "in-memory promotion must still happen"


def test_make_grounder_only_reports_a_persist_failure_once(monkeypatch, capsys):
    # A repeated failure (e.g. the db staying locked for several ticks) must
    # not spam the console once per tick.
    monkeypatch.setattr(grounding, "iter_elements", lambda title_re: EN)
    from ghostcursor.perception.appinfo import AppInfo

    app_info = AppInfo(
        app_id="app.exe", exe_path=r"C:\app.exe", version="1.0", kind="win32"
    )
    grounder = make_grounder(
        ".*", app_info=app_info, store=_RaisingStore(), recipe_intent="do a thing"
    )

    for _ in range(3):
        grounder(_step(), 0)

    printed = capsys.readouterr().out
    assert printed.count("Persistence disabled") == 1


# --- finding 1 (whole-branch review): overlay teardown and ESC pre-tour -----


def _fake_recipe():
    return Recipe(app_id="app", intent="do a thing", steps=[])


class _FakeAppInfo:
    app_id = "app.exe"
    version = "1.0"


class _RaisingObservationStore:
    def __init__(self, *a, **kw):
        raise sqlite3.OperationalError("unable to open database file")


def test_run_tour_destroys_overlay_when_store_construction_raises(
    monkeypatch, tmp_path
):
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text("{}", encoding="utf-8")

    destroyed = []
    monkeypatch.setattr(window, "create_overlay_window", lambda: 4242)
    monkeypatch.setattr(
        window, "destroy_overlay_window", lambda hwnd: destroyed.append(hwnd)
    )
    monkeypatch.setattr(window, "pump_messages_nonblocking", lambda: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
    monkeypatch.setattr(Recipe, "load", staticmethod(lambda path: _fake_recipe()))
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda title_re: _FakeAppInfo())

    import ghostcursor.memory.store as store_module

    monkeypatch.setattr(store_module, "ObservationStore", _RaisingObservationStore)

    with pytest.raises(sqlite3.OperationalError):
        run_module.run_tour(str(recipe_path), ".*", 5.0)

    assert destroyed == [4242], (
        "the overlay must always be torn down, even when ObservationStore() "
        "raises -- a stranded full-screen overlay is the exact failure the "
        "finally block exists to prevent"
    )


def test_run_tour_exits_cleanly_when_esc_is_pressed_before_the_tour_starts(
    monkeypatch, tmp_path
):
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text("{}", encoding="utf-8")

    destroyed = []
    monkeypatch.setattr(window, "create_overlay_window", lambda: 4242)
    monkeypatch.setattr(
        window, "destroy_overlay_window", lambda hwnd: destroyed.append(hwnd)
    )
    monkeypatch.setattr(window, "pump_messages_nonblocking", lambda: None)
    monkeypatch.setattr(Recipe, "load", staticmethod(lambda path: _fake_recipe()))
    # None means "no application identity" -- ObservationStore must never be
    # constructed on this path, so leaving it unpatched would blow up loudly
    # if the code tried.
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda title_re: None)

    # False on the first pre-tour check (right after overlay creation), True
    # on the second (right after the app-info lookup) -- proves ESC aborts a
    # slow pre-tour phase rather than only being checked once at the top.
    calls = iter([False, True])
    monkeypatch.setattr(run_module, "escape_pressed", lambda: next(calls))

    def _boom_if_constructed(*a, **kw):
        raise AssertionError("GuidedTour must not be constructed after ESC")

    # run_tour imports GuidedTour locally from ghostcursor.reasoning.loop, so
    # patching the attribute there (rather than on run_module) is what
    # actually intercepts it.
    import ghostcursor.reasoning.loop as loop_module

    monkeypatch.setattr(loop_module, "GuidedTour", _boom_if_constructed)

    result = run_module.run_tour(str(recipe_path), ".*", 5.0)

    assert result == 0
    assert destroyed == [4242]
