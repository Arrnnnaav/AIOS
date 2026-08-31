"""Native manager window checks. Run alone under D025."""

import win32con
import win32gui

from ghostcursor.manager import (
    ID_DETAILS,
    ID_COMPLEX,
    ID_GOAL,
    ID_INSTRUCTION,
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
)
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
        assert win32gui.GetWindowText(manager._controls[ID_INSTRUCTION]) == "Click Open Folder."
        assert "Slide Title  GhostCursor" in win32gui.GetWindowText(
            manager._controls[ID_DETAILS]
        )
        assert win32gui.IsWindowEnabled(manager._controls[ID_PAUSE])
        assert win32gui.IsWindowEnabled(manager._controls[ID_STOP])
        assert win32gui.SendMessage(
            manager._controls[ID_TIMELINE], win32con.LB_GETCOUNT, 0, 0
        ) == 2
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

        manager._on_command(ID_COMPLEX)
        request = manager.take_request()
        assert request == TaskProposalRequest(
            "Build an investor deck", "ghostcursor.powerpoint"
        )
        assert manager.take_request() is None

        manager.show_task_proposal("Build an investor deck", proposal)
        assert win32gui.GetWindowText(manager._controls[ID_COMPLEX]) == "Start plan"
        assert win32gui.SendMessage(
            manager._controls[ID_TIMELINE], win32con.LB_GETCOUNT, 0, 0
        ) == 2
        assert manager.take_request() is None

        manager._on_command(ID_COMPLEX)
        assert manager.take_request() == TaskExecutionRequest(
            "Build an investor deck", graph
        )
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
