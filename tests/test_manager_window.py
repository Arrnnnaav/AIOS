"""Native manager window checks. Run alone under D025."""

import win32con
import win32gui

from ghostcursor.manager import (
    ID_DETAILS,
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
)
from ghostcursor.session import (
    GuidanceValue,
    SessionSnapshot,
    SessionStatus,
    active_capabilities,
)


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
