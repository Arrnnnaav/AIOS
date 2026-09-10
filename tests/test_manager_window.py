"""Native manager window checks. Run alone under D025."""

from pathlib import Path
from types import SimpleNamespace

import win32con
import win32gui

from ghostcursor import manager as manager_module

from ghostcursor.manager import (
    ActExecutionRequest,
    ActProposalRequest,
    ID_DETAILS,
    ID_COMPLEX,
    ID_GOAL,
    ID_INSTRUCTION,
    ID_LAYOUT,
    ID_MODE,
    ID_MODE_NOTE,
    ID_PAUSE,
    ID_PLUGINS,
    ID_PROGRESS,
    ID_STATUS,
    ID_START,
    ID_STOP,
    ID_TIMELINE,
    NativeManagerWindow,
    PluginPresentation,
    TaskExecutionRequest,
    TaskProposalRequest,
    _consume_act_execution_request,
    _manager_bounds,
)
from ghostcursor.interaction import MODE_ORDER, InteractionMode
from ghostcursor.session import (
    GuidanceValue,
    SessionSnapshot,
    SessionStatus,
    active_capabilities,
)
from ghostcursor.task_planner import TaskPlanStep


def _snapshot(status=SessionStatus.GUIDING, guidance_values=()):
    return SessionSnapshot(
        session_id="native-session",
        status=status,
        goal="Open a folder",
        plugin_id="ghostcursor.vscode",
        plugin_version="1.0.0",
        application="Code.exe",
        current_step=1,
        total_steps=2,
        plan_steps=("Open Folder", "Choose a folder"),
        instruction="Click Open Folder.",
        guidance_values=guidance_values,
        capabilities=active_capabilities(paused=status is SessionStatus.PAUSED),
    )


def _choose_mode(manager, mode):
    win32gui.SendMessage(
        manager._controls[ID_MODE],
        win32con.CB_SETCURSEL,
        MODE_ORDER.index(mode),
        0,
    )
    manager._on_command(ID_MODE)


def _window_bounds(hwnd):
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return left, top, right - left, bottom - top


def test_manager_starts_as_a_right_rail_and_expands_the_same_window():
    manager = NativeManagerWindow()
    try:
        original_hwnd = manager.hwnd
        goal = "Build a reviewed deck"
        win32gui.SetWindowText(manager._controls[ID_GOAL], goal)

        assert manager.expanded is False
        assert _window_bounds(manager.hwnd) == _manager_bounds(False)
        assert win32gui.GetWindowText(manager._controls[ID_LAYOUT]) == "Expand"
        assert win32gui.IsWindowVisible(manager._controls[ID_INSTRUCTION])
        assert not win32gui.IsWindowVisible(manager._controls[ID_TIMELINE])
        assert not win32gui.IsWindowVisible(manager._controls[ID_PLUGINS])

        manager._on_command(ID_LAYOUT)

        assert manager.hwnd == original_hwnd
        assert manager.expanded is True
        assert _window_bounds(manager.hwnd) == _manager_bounds(True)
        assert win32gui.GetWindowText(manager._controls[ID_LAYOUT]) == "Collapse"
        assert win32gui.IsWindowVisible(manager._controls[ID_TIMELINE])
        assert win32gui.IsWindowVisible(manager._controls[ID_PLUGINS])
        assert win32gui.GetWindowText(manager._controls[ID_GOAL]) == goal

        manager._on_command(ID_LAYOUT)

        assert manager.hwnd == original_hwnd
        assert manager.expanded is False
        assert _window_bounds(manager.hwnd) == _manager_bounds(False)
        assert win32gui.GetWindowText(manager._controls[ID_GOAL]) == goal
    finally:
        manager.dispose()


def test_manager_expands_for_planning_and_for_an_actionable_failure():
    manager = NativeManagerWindow()
    try:
        assert manager.expanded is False

        manager.show_understanding("Add a slide in PowerPoint")
        assert manager.expanded is True

        manager._on_command(ID_LAYOUT)
        assert manager.expanded is False
        manager.show_unavailable("", "PowerPoint is not running")
        assert manager.expanded is True
    finally:
        manager.dispose()


def test_manual_expand_during_execution_is_not_undone_by_progress_events():
    manager = NativeManagerWindow()
    try:
        manager._on_command(ID_LAYOUT)
        assert manager.expanded is True

        event = SimpleNamespace(
            ordinal=7,
            total=12,
            operation_id="add_text",
            detail="Adding the headline",
        )
        manager.show_act_event(event)

        assert manager.expanded is True
        assert win32gui.GetWindowText(manager._controls[ID_PROGRESS]) == (
            "Action 7 of 12"
        )
    finally:
        manager.dispose()


def test_failed_act_result_reopens_the_workspace_but_success_stays_compact():
    manager = NativeManagerWindow()
    try:
        failed = SimpleNamespace(
            completed=False,
            completed_node_ids=("node-1",),
            detail="Verification refused",
            code=SimpleNamespace(value="verification_failed"),
            output_path=None,
        )
        manager.show_act_result(failed)
        assert manager.expanded is True

        completed = SimpleNamespace(
            completed=True,
            completed_node_ids=("node-1", "node-2"),
            detail="Completed",
            code=SimpleNamespace(value="completed"),
            output_path="D:\\output.pptx",
        )
        manager.show_act_result(completed)
        assert manager.expanded is False
    finally:
        manager.dispose()


def test_manager_is_a_normal_non_topmost_window_and_renders_snapshot_truth():
    manager = NativeManagerWindow()
    try:
        ex_style = win32gui.GetWindowLong(manager.hwnd, win32con.GWL_EXSTYLE)
        style = win32gui.GetWindowLong(manager.hwnd, win32con.GWL_STYLE)
        assert not (ex_style & win32con.WS_EX_TOPMOST)
        assert style & win32con.WS_OVERLAPPEDWINDOW

        manager.render_snapshot(
            _snapshot(guidance_values=(GuidanceValue("slide_title", "GhostCursor"),))
        )
        assert win32gui.GetWindowText(manager._controls[ID_STATUS]) == "Guiding"
        assert win32gui.GetWindowText(manager._controls[ID_GOAL]) == "Open a folder"
        assert not win32gui.IsWindowEnabled(manager._controls[ID_GOAL])
        assert win32gui.GetWindowText(manager._controls[ID_PROGRESS]) == "Step 1 of 2"
        assert (
            win32gui.GetWindowText(manager._controls[ID_INSTRUCTION])
            == "Click Open Folder."
        )
        assert "Slide Title  GhostCursor" in win32gui.GetWindowText(
            manager._controls[ID_DETAILS]
        )
        assert win32gui.IsWindowEnabled(manager._controls[ID_PAUSE])
        assert win32gui.IsWindowEnabled(manager._controls[ID_STOP])
        assert (
            win32gui.SendMessage(
                manager._controls[ID_TIMELINE], win32con.LB_GETCOUNT, 0, 0
            )
            == 2
        )
    finally:
        manager.dispose()


def test_manager_plugin_rows_render_the_store_reported_state_verbatim():
    manager = NativeManagerWindow()
    try:
        manager.set_plugins(
            (
                PluginPresentation(
                    "ghostcursor.vscode",
                    "1.0.0",
                    "blocked_incompatible",
                    "core outside range",
                ),
            )
        )
        count = win32gui.SendMessage(
            manager._controls[ID_PLUGINS], win32con.LB_GETCOUNT, 0, 0
        )
        assert count == 1
        assert "blocked_incompatible" in manager._plugin_rows[0]
        assert "core outside range" in manager._plugin_rows[0]
    finally:
        manager.dispose()


def test_manager_mode_selector_exposes_act_as_review_then_approve():
    manager = NativeManagerWindow()
    try:
        assert win32gui.SendMessage(
            manager._controls[ID_MODE], win32con.CB_GETCOUNT, 0, 0
        ) == len(MODE_ORDER)
        assert win32gui.GetWindowText(manager._controls[ID_MODE]) == "Teach"
        assert win32gui.IsWindowEnabled(manager._controls[ID_START])
        assert not win32gui.IsWindowEnabled(manager._controls[ID_COMPLEX])

        manager.set_plugins(
            (
                PluginPresentation(
                    "ghostcursor.powerpoint",
                    "1.0.0",
                    "enabled_compatible",
                    "compatible",
                    True,
                ),
            )
        )
        win32gui.SendMessage(manager._controls[ID_PLUGINS], win32con.LB_SETCURSEL, 0, 0)
        _choose_mode(manager, InteractionMode.ACT)

        assert "Ready" == win32gui.GetWindowText(manager._controls[ID_STATUS])
        assert "Review one complete signed plan" in win32gui.GetWindowText(
            manager._controls[ID_MODE_NOTE]
        )
        assert win32gui.IsWindowEnabled(manager._controls[ID_START])
        assert not win32gui.IsWindowEnabled(manager._controls[ID_COMPLEX])
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Do this on your own")
        manager._on_command(ID_START)
        request = manager.take_request()
        assert request.goal == "Do this on your own"
        assert request.output_path.suffix == ".pptx"
    finally:
        manager.dispose()


def test_terminal_act_result_cannot_replay_the_previous_approval():
    from types import SimpleNamespace

    manager = NativeManagerWindow()
    try:
        _choose_mode(manager, InteractionMode.ACT)
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Build an investor deck")
        manager.show_act_proposal(
            "Build an investor deck",
            SimpleNamespace(
                summary="Build the reviewed deck",
                graph=SimpleNamespace(nodes=()),
                steps=("Create the presentation", "Save and verify it"),
            ),
        )
        manager.show_act_result(
            SimpleNamespace(
                completed=True,
                completed_node_ids=("save",),
                detail="saved and verified",
                code=SimpleNamespace(value="completed"),
                output_path=Path("deck.pptx"),
            )
        )

        manager._on_command(ID_START)
        request = manager.take_request()
        assert isinstance(request, ActProposalRequest)
        assert request.goal == "Build an investor deck"
        assert request.output_path.suffix == ".pptx"
    finally:
        manager.dispose()


def test_approve_and_run_issues_one_exact_request_for_the_displayed_proposal(
    monkeypatch,
):
    from types import SimpleNamespace

    proposal = SimpleNamespace(
        summary="Add one slide",
        graph=SimpleNamespace(nodes=(object(),)),
        steps=("Add slide",),
        target=SimpleNamespace(hwnd=654),
    )
    handed_off = []
    monkeypatch.setattr(
        "ghostcursor.manager.restore_focus_if_safe",
        lambda owner, target: handed_off.append((owner, target)) or True,
    )
    manager = NativeManagerWindow()
    try:
        _choose_mode(manager, InteractionMode.ACT)
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Add a slide")
        manager.show_act_proposal("Add a slide", proposal)
        assert manager.expanded is True
        displayed = manager.take_act_audit_records()

        manager._on_command(ID_START)
        request = manager.take_request()
        approved = manager.take_act_audit_records()

        assert type(request) is ActExecutionRequest
        assert request.goal == "Add a slide"
        assert manager.expanded is False
        assert handed_off == [(manager.hwnd, 654)]
        assert [record.type for record in displayed] == ["act_proposal_displayed"]
        assert [record.type for record in approved] == [
            "target_focus_handoff_completed",
            "approve_and_run_issued",
        ]
        assert all(
            displayed[0].proposal_sha256 == record.proposal_sha256
            for record in approved
        )
        assert displayed[0].validation_sha256 is None
        assert "Add a slide" not in repr(displayed[0])
        assert _consume_act_execution_request(request) is proposal
        assert manager.take_request() is None
    finally:
        manager.dispose()


def test_refused_target_focus_handoff_issues_no_act_request(monkeypatch):
    from types import SimpleNamespace

    proposal = SimpleNamespace(
        summary="Add one slide",
        graph=SimpleNamespace(nodes=(object(),)),
        steps=("Add slide",),
        target=SimpleNamespace(hwnd=654),
    )
    handed_off = []
    monkeypatch.setattr(
        "ghostcursor.manager.restore_focus_if_safe",
        lambda owner, target: handed_off.append((owner, target)) or False,
    )
    manager = NativeManagerWindow()
    try:
        _choose_mode(manager, InteractionMode.ACT)
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Add a slide")
        manager.show_act_proposal("Add a slide", proposal)
        manager.take_act_audit_records()

        manager._on_command(ID_START)

        assert handed_off == [(manager.hwnd, 654)]
        assert manager.take_request() is None
        refused = manager.take_act_audit_records()
        assert [record.type for record in refused] == [
            "approve_and_run_handoff_refused"
        ]
        assert refused[0].code == "target_focus_handoff_refused"
        assert refused[0].completed is False
        assert manager._act_proposal is proposal
        assert win32gui.IsWindowEnabled(manager._controls[ID_START])
        assert "not activated" in win32gui.GetWindowText(manager._controls[ID_STATUS])
    finally:
        manager.dispose()


def test_a_non_integer_hwnd_is_refused_before_any_win32_call(monkeypatch):
    """The `type(hwnd) is int` guard, pinned on its own.

    Relaxing it to `hwnd is None` survived a mutation audit because no test
    supplied anything else. A string handle then reaches `win32gui.IsWindow`
    and raises `TypeError` inside `WM_COMMAND` -- a crash in the message
    pump, not the clean refusal D123 requires.
    """

    from types import SimpleNamespace

    proposal = SimpleNamespace(
        summary="Add one slide",
        graph=SimpleNamespace(nodes=(object(),)),
        steps=("Add slide",),
        target=SimpleNamespace(hwnd="654"),
    )
    attempts = []
    monkeypatch.setattr(
        "ghostcursor.manager.restore_focus_if_safe",
        lambda owner, target: attempts.append((owner, target)) or True,
    )
    manager = NativeManagerWindow()
    try:
        _choose_mode(manager, InteractionMode.ACT)
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Add a slide")
        manager.show_act_proposal("Add a slide", proposal)
        manager.take_act_audit_records()

        manager._on_command(ID_START)

        assert attempts == []
        assert manager.take_request() is None
        refused = manager.take_act_audit_records()
        assert [record.type for record in refused] == [
            "approve_and_run_handoff_refused"
        ]
        assert manager._act_proposal is proposal
    finally:
        manager.dispose()


def test_the_handoff_is_recorded_before_the_request_is_minted(monkeypatch):
    """Ordering the retained transcript can actually evidence.

    The handoff happens before issuance either way, but a reviewer reads the
    JSONL, not the source. With the record emitted after `_issue_...`, the
    transcript looks the same whether or not the handoff came first, so the
    ordering claim rested on reading code. Recording the sequence counter as
    issuance begins makes the artifact carry the fact.
    """

    from types import SimpleNamespace

    proposal = SimpleNamespace(
        summary="Add one slide",
        graph=SimpleNamespace(nodes=(object(),)),
        steps=("Add slide",),
        target=SimpleNamespace(hwnd=654),
    )
    monkeypatch.setattr(
        "ghostcursor.manager.restore_focus_if_safe", lambda owner, target: True
    )
    manager = NativeManagerWindow()
    original = manager_module._issue_act_execution_request
    at_issue = []

    def watched(goal, value):
        at_issue.append(manager._act_audit_sequence)
        return original(goal, value)

    monkeypatch.setattr("ghostcursor.manager._issue_act_execution_request", watched)
    try:
        _choose_mode(manager, InteractionMode.ACT)
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Add a slide")
        manager.show_act_proposal("Add a slide", proposal)
        manager.take_act_audit_records()

        manager._on_command(ID_START)

        records = {r.type: r for r in manager.take_act_audit_records()}
        assert at_issue, "the execution request was never issued"
        handoff = records["target_focus_handoff_completed"]
        issued = records["approve_and_run_issued"]
        # The handoff record already existed when issuance began; the
        # issuance record did not.
        assert handoff.sequence <= at_issue[0]
        assert issued.sequence > at_issue[0]
    finally:
        manager.dispose()


def test_exported_audit_commitments_are_keyed_not_bare_hashes():
    """A bare SHA-256 over a target binding is reversible in practice.

    The binding is an executable name, a version, an HWND and a PID, and the
    evidence documents publish the first two. Roughly 2**39 candidates remain,
    which is minutes of GPU work -- so an unkeyed digest hands back exactly
    the HWND and PID D122 keeps out of the record.
    """

    import hashlib
    import json
    from types import SimpleNamespace

    target = SimpleNamespace(
        executable="POWERPNT.EXE",
        executable_version="16.0.20326.20112",
        hwnd=770001,
        pid=880002,
    )
    proposal = SimpleNamespace(
        summary="Add one slide",
        graph=SimpleNamespace(nodes=(object(),)),
        steps=("Add slide",),
        target=target,
        intent_id="ADD_SLIDE",
    )
    facts = manager_module._proposal_audit_facts("Add a slide", proposal)

    bare = hashlib.sha256(
        json.dumps(
            {
                "executable": "powerpnt.exe",
                "executable_version": "16.0.20326.20112",
                "hwnd": 770001,
                "pid": 880002,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert facts["target_sha256"] != bare
    assert facts["proposal_sha256"] != bare
    # Still a commitment: the same binding correlates inside one transcript.
    assert (
        manager_module._proposal_audit_facts("Add a slide", proposal)["target_sha256"]
        == facts["target_sha256"]
    )
    # ...and a different handle does not collide with it.
    other = SimpleNamespace(
        summary="Add one slide",
        graph=SimpleNamespace(nodes=(object(),)),
        steps=("Add slide",),
        target=SimpleNamespace(
            executable="POWERPNT.EXE",
            executable_version="16.0.20326.20112",
            hwnd=770002,
            pid=880002,
        ),
        intent_id="ADD_SLIDE",
    )
    assert (
        manager_module._proposal_audit_facts("Add a slide", other)["target_sha256"]
        != facts["target_sha256"]
    )


def test_every_exported_audit_digest_is_keyed_including_the_scalar_helper():
    """`_audit_commitment` covers the structural digests; `_audit_digest`
    covers the scalar ones -- an output path, a goal, an executor detail --
    and those are guessable too. An independent review pointed out that the
    earlier mutation audit had broken the helper the production commitments do
    not use, so the scalar path was never actually pinned.
    """

    import hashlib

    value = r"D:\decks\investor.pptx"
    bare = hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    assert manager_module._audit_digest(value) != bare
    # Same input, same digest inside one process: still a commitment.
    assert manager_module._audit_digest(value) == manager_module._audit_digest(value)
    assert manager_module._audit_digest(value + "x") != manager_module._audit_digest(value)


def test_the_two_digest_helpers_do_not_share_an_unkeyed_fallback():
    """Both helpers must key. A single unkeyed one is enough to expose the
    binding, because the fields flow into the same records."""

    import hashlib
    import json

    binding = {"executable": "powerpnt.exe", "hwnd": 770001}
    bare = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assert manager_module._audit_commitment(binding) != bare


def test_identical_titles_are_chosen_by_handle_and_returned_only_as_narrowing():
    from types import SimpleNamespace

    manager = NativeManagerWindow()
    try:
        candidates = tuple(
            SimpleNamespace(
                hwnd=hwnd,
                title="same - PowerPoint",
                app=SimpleNamespace(executable_name="POWERPNT.EXE", version="16.0"),
            )
            for hwnd in (101, 202)
        )
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Create a project update")
        manager.show_target_choices("Create a project update", candidates)
        win32gui.SendMessage(
            manager._controls[ID_TIMELINE], win32con.LB_SETCURSEL, 1, 0
        )
        manager._on_command(ID_START)

        request = manager.take_launch_request()
        assert request.goal == "Create a project update"
        assert request.target_hwnd == 202
    finally:
        manager.dispose()


def test_complex_goal_requires_plugin_selection_then_a_second_explicit_start():
    from types import SimpleNamespace

    manager = NativeManagerWindow()
    try:
        graph = object()
        proposal = SimpleNamespace(
            graph=graph,
            summary="Build a reviewed investor deck.",
            steps=(
                TaskPlanStep("theme", "APPLY_THEME", "apply the approved theme"),
                TaskPlanStep("title", "ADD_TITLE", "add the title slide"),
            ),
        )
        manager.set_plugins(
            (
                PluginPresentation(
                    "ghostcursor.powerpoint",
                    "1.0.0",
                    "enabled_compatible",
                    "compatible",
                    True,
                ),
            )
        )
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Build an investor deck")
        win32gui.SendMessage(manager._controls[ID_PLUGINS], win32con.LB_SETCURSEL, 0, 0)
        _choose_mode(manager, InteractionMode.PLAN)

        manager._on_command(ID_COMPLEX)
        request = manager.take_request()
        assert request == TaskProposalRequest(
            "Build an investor deck", "ghostcursor.powerpoint"
        )
        assert manager.take_request() is None

        manager.show_task_proposal("Build an investor deck", proposal)
        assert manager.expanded is True
        assert win32gui.GetWindowText(manager._controls[ID_COMPLEX]) == "Start plan"
        assert (
            win32gui.SendMessage(
                manager._controls[ID_TIMELINE], win32con.LB_GETCOUNT, 0, 0
            )
            == 2
        )
        assert manager.take_request() is None

        manager._on_command(ID_COMPLEX)
        assert manager.take_request() == TaskExecutionRequest(
            "Build an investor deck", graph
        )
        assert manager.expanded is False
    finally:
        manager.dispose()


def test_complex_target_choice_reuses_reviewed_graph_and_selected_handle():
    from types import SimpleNamespace

    manager = NativeManagerWindow()
    try:
        graph = object()
        proposal = SimpleNamespace(
            graph=graph,
            summary="Build a deck.",
            steps=(TaskPlanStep("title", "ADD_TITLE", "add a title"),),
        )
        candidates = tuple(
            SimpleNamespace(
                hwnd=hwnd,
                title="same - PowerPoint",
                app=SimpleNamespace(executable_name="POWERPNT.EXE", version="16.0"),
            )
            for hwnd in (101, 202)
        )
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Build an investor deck")
        manager.show_task_proposal("Build an investor deck", proposal)
        manager.show_task_target_choices(candidates)
        win32gui.SendMessage(
            manager._controls[ID_TIMELINE], win32con.LB_SETCURSEL, 1, 0
        )

        manager._on_command(ID_COMPLEX)

        assert manager.take_request() == TaskExecutionRequest(
            "Build an investor deck", graph, 202
        )
    finally:
        manager.dispose()


def test_missing_target_retries_the_reviewed_graph_not_the_simple_goal_path():
    from types import SimpleNamespace

    manager = NativeManagerWindow()
    try:
        graph = object()
        proposal = SimpleNamespace(
            graph=graph,
            summary="Build a deck.",
            steps=(TaskPlanStep("title", "ADD_TITLE", "add a title"),),
        )
        win32gui.SetWindowText(manager._controls[ID_GOAL], "Build an investor deck")
        manager.show_task_proposal("Build an investor deck", proposal)
        manager.show_target_not_running(
            "Build an investor deck", "PowerPoint is not running"
        )

        assert not win32gui.IsWindowEnabled(manager._controls[ID_START])
        assert not win32gui.IsWindowEnabled(manager._controls[ID_GOAL])
        assert win32gui.GetWindowText(manager._controls[ID_COMPLEX]) == "Retry plan"
        manager._on_command(ID_COMPLEX)
        assert manager.take_request() == TaskExecutionRequest(
            "Build an investor deck", graph
        )
    finally:
        manager.dispose()
