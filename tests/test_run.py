"""Covers findings 2 and 4 from the whole-branch review of the tour path:

- finding 2: the grounder wired into a live compiled tour must call
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
from ghostcursor.perception import appinfo, uia
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
from ghostcursor.run import (
    confirmation_focus_is_safe,
    key_was_pressed,
    make_grounder,
    space_confirmation_requested,
    should_poll_space,
)

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


def test_space_requires_the_target_hwnd_to_own_foreground(monkeypatch):
    monkeypatch.setattr(run_module.win32gui, "GetForegroundWindow", lambda: 42)
    assert confirmation_focus_is_safe(42, 99) is True
    assert confirmation_focus_is_safe(43, 99) is False
    assert confirmation_focus_is_safe(42, 42) is False


def test_live_confirmation_reads_space_only_with_safe_target_focus(monkeypatch):
    reads = []
    monkeypatch.setattr(run_module.win32gui, "GetForegroundWindow", lambda: 42)
    monkeypatch.setattr(
        run_module.win32api,
        "GetAsyncKeyState",
        lambda vk: reads.append(vk) or _CURRENTLY_DOWN,
    )

    assert space_confirmation_requested(42, 99) is True
    assert reads == [run_module.win32con.VK_SPACE]

    reads.clear()
    assert space_confirmation_requested(43, 99) is False
    assert reads == [], "SPACE was consumed while another window owned focus"


def test_space_is_blocked_when_target_hwnd_is_unknown(monkeypatch):
    monkeypatch.setattr(run_module.win32gui, "GetForegroundWindow", lambda: 42)
    assert confirmation_focus_is_safe(0, None) is False


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


def test_vscode_recipe_selects_the_targeted_perception_walker():
    from ghostcursor.perception.compiled import compiled_plan_runner
    from tests.test_compiled_workflow import _workflow

    workflow, _ = _workflow()
    calls = []
    compiled_plan_runner(
        workflow,
        walk=lambda hwnd, control_type: calls.append((hwnd, control_type)) or [],
        query=lambda *args: [],
        read_title=lambda _hwnd: workflow.target.title,
    )(workflow.target.hwnd)
    assert calls == [(workflow.target.hwnd, "Button")]
def test_executable_recipe_selects_an_identity_bounded_hwnd_source():
    from ghostcursor.perception.compiled import compiled_perception_service
    from tests.test_compiled_workflow import _workflow

    workflow, _ = _workflow()
    service = compiled_perception_service(workflow, lambda: 0.0)
    assert service.hwnd_source("a title that must be ignored") == workflow.target.hwnd
def test_run_tour_never_creates_overlay_when_revalidation_raises():
    from pathlib import Path
    from tests.test_compiled_workflow import _workflow
    import ghostcursor.run as run_module

    workflow, _ = _workflow()
    created = []
    with pytest.raises(RuntimeError, match="reload failed"):
        run_module._launch_compiled_workflow(
            workflow, seconds=1.0,
            reload_catalog=lambda: (_ for _ in ()).throw(RuntimeError("reload failed")),
            read_window=lambda _hwnd: None,
            project_root=Path(__file__).resolve().parents[1],
            clock=lambda: 0.0, sleeper=lambda _s: None,
            warmup_budget_s=0.0,
            create_overlay=lambda: created.append(True),
        )
    assert created == []
def test_run_tour_exits_cleanly_when_esc_is_pressed_before_the_tour_starts(monkeypatch):
    from tests.test_compiled_workflow import _workflow
    import ghostcursor.run as run_module

    workflow, _ = _workflow()
    created = []
    monkeypatch.setattr(run_module, "escape_pressed", lambda: True)
    result = run_module._run_compiled_tour(
        workflow, seconds=1.0, clock=lambda: 0.0, sleeper=lambda _s: None,
        warmup_budget_s=0.0, create_overlay=lambda: created.append(True),
        renderer=type("Renderer", (), {"show":lambda *a:None, "clear":lambda *a:None, "settle":lambda *a:None})(),
        observe=lambda: None,
    )
    assert result == 0
    assert created == []
def test_run_tour_creates_overlay_only_after_live_revalidation():
    from tests.test_compiled_workflow import PROJECT_ROOT, _window, _workflow
    import ghostcursor.run as run_module

    workflow, catalog = _workflow()
    order = []
    def read_window(hwnd):
        order.append("read_window")
        return _window(hwnd=hwnd)
    def create_overlay():
        order.append("create_overlay")
        raise RuntimeError("stop after ordering proof")

    with pytest.raises(RuntimeError, match="ordering proof"):
        run_module._launch_compiled_workflow(
            workflow, seconds=1.0, reload_catalog=lambda: catalog,
            read_window=read_window, project_root=PROJECT_ROOT,
            clock=lambda: 0.0, sleeper=lambda _s: None,
            warmup_budget_s=0.0, create_overlay=create_overlay,
        )
    assert order == ["read_window", "create_overlay"]
def test_grounder_reports_uia_provenance_when_debug_is_on(monkeypatch, capsys):
    """Gate 2 resets on any OCR-grounded run, so provenance must be observable.

    Without this the run reports only "Tour complete.", which is exactly the
    outcome-only signal that let Open Folder's tier-1 perception go dark. The
    line is diagnostic and stays behind the existing debug switch.
    """
    monkeypatch.setenv("GHOSTCURSOR_DEBUG_PERCEPTION", "1")
    monkeypatch.setattr(grounding, "iter_elements", lambda title_re: EN)

    grounder = make_grounder(".*")
    grounder(_step(), 0)

    out = capsys.readouterr().out
    assert "provenance" in out.lower()
    assert "uia" in out.lower()


def test_grounder_reports_ocr_provenance_distinctly(monkeypatch, capsys):
    """An OCR-grounded step must be distinguishable, not just 'grounded'."""
    from ghostcursor.perception.uia import Element

    ocr_only = [Element("Export", "", "", (10, 10, 110, 40), source="ocr")]
    monkeypatch.setenv("GHOSTCURSOR_DEBUG_PERCEPTION", "1")
    monkeypatch.setattr(grounding, "iter_elements", lambda title_re: ocr_only)

    grounder = make_grounder(".*")
    result = grounder(_step(), 0)

    out = capsys.readouterr().out
    if result is not None:
        assert "ocr" in out.lower()


def test_grounder_stays_quiet_without_the_debug_switch(monkeypatch, capsys):
    monkeypatch.delenv("GHOSTCURSOR_DEBUG_PERCEPTION", raising=False)
    monkeypatch.setattr(grounding, "iter_elements", lambda title_re: EN)

    grounder = make_grounder(".*")
    grounder(_step(), 0)

    assert "provenance" not in capsys.readouterr().out.lower()
