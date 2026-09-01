"""Single-process native manager for goals, sessions, plugins, and recovery.

The manager is intentionally a normal, non-topmost application window.  The
small control rail remains the in-tour safety surface; both consume the same
executor-owned session snapshots and send edge-triggered commands through the
same-process mailbox.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import win32api
import win32con
import win32gui

from ghostcursor.interaction import (
    MODE_ORDER,
    InteractionMode,
    mode_can_propose_plan,
    mode_can_start_guidance,
    mode_contract,
    mode_label,
)
from ghostcursor.overlay.window import ensure_class, pump_messages_nonblocking
from ghostcursor.session import (
    SessionCommand,
    SessionSnapshot,
    SessionStatus,
    session_commands,
    session_events,
)


MANAGER_CLASS_NAME = "GhostCursorManager"
MANAGER_TITLE = "GhostCursor"
MANAGER_WIDTH = 980
MANAGER_HEIGHT = 680

COLOR_BACKGROUND = win32api.RGB(15, 17, 22)
COLOR_SURFACE = win32api.RGB(27, 30, 38)
COLOR_TEXT = win32api.RGB(238, 241, 247)
COLOR_MUTED = win32api.RGB(153, 161, 176)
COLOR_ACCENT = win32api.RGB(58, 139, 253)

ID_GOAL = 2101
ID_START = 2102
ID_TIMELINE = 2103
ID_STATUS = 2104
ID_PROGRESS = 2105
ID_INSTRUCTION = 2106
ID_VERIFICATION = 2107
ID_PAUSE = 2108
ID_STOP = 2109
ID_PLUGINS = 2110
ID_DETAILS = 2111
ID_PRIVACY = 2112
ID_COMPLEX = 2113
ID_MODE = 2114
ID_MODE_NOTE = 2115
ID_HEADER = 2190
ID_PLAN_LABEL = 2191
ID_GUIDANCE_LABEL = 2192
ID_VERIFICATION_LABEL = 2193
ID_PLUGINS_LABEL = 2194
ID_DETAILS_LABEL = 2195
ID_MODE_LABEL = 2196
ID_GOAL_LABEL = 2197
DEFAULT_GUI_FONT = 17

_background_brush = None
_surface_brush = None
_windows: dict[int, "NativeManagerWindow"] = {}


_STATUS_LABELS = {
    SessionStatus.UNDERSTANDING: "Understanding your goal",
    SessionStatus.TARGET_NOT_RUNNING: "Application not running",
    SessionStatus.TARGET_CHOICE_REQUIRED: "Choose an application window",
    SessionStatus.PLAN_VALIDATING: "Checking the complete plan",
    SessionStatus.PLAN_REJECTED: "Plan needs revision",
    SessionStatus.READY_TO_START: "Ready to start",
    SessionStatus.GUIDING: "Guiding",
    SessionStatus.WAITING_FOR_USER: "Waiting for you",
    SessionStatus.VERIFYING: "Checking the result",
    SessionStatus.PAUSED: "Paused",
    SessionStatus.BLOCKED: "Needs attention",
    SessionStatus.COMPLETED: "Goal completed",
    SessionStatus.STOPPED: "Stopped",
    SessionStatus.FAILED: "Could not complete",
}


@dataclass(frozen=True)
class ManagerStep:
    number: int
    instruction: str
    state: str


@dataclass(frozen=True)
class ManagerProjection:
    status: str
    goal: str
    application: str
    progress: str
    instruction: str
    verification: str
    steps: tuple[ManagerStep, ...]
    details: str
    can_pause: bool
    can_stop: bool
    paused: bool


@dataclass(frozen=True)
class PluginPresentation:
    plugin_id: str
    version: str
    state: str
    compatibility: str
    has_capabilities: bool = False


@dataclass(frozen=True)
class LaunchRequest:
    goal: str
    target_hwnd: int | None = None


@dataclass(frozen=True)
class TaskProposalRequest:
    goal: str
    plugin_id: str


@dataclass(frozen=True)
class TaskExecutionRequest:
    goal: str
    graph: object
    target_hwnd: int | None = None


@dataclass(frozen=True)
class PlanningResult:
    request: LaunchRequest | TaskProposalRequest
    result: object | None
    error: BaseException | None


def task_preview_rows(proposal: object) -> tuple[str, ...]:
    """Flatten one already-validated proposal for review, never execution."""

    rows = []
    for number, step in enumerate(getattr(proposal, "steps"), start=1):
        guidance = ", ".join(
            f"{value.name.replace('_', ' ')}={value.value}"
            for value in step.guidance_values
        )
        suffix = f" · {guidance}" if guidance else ""
        rows.append(f"○  {number}. {step.instruction}{suffix}")
    return tuple(rows)


def task_result_action(result: object) -> str:
    """Choose UI recovery without ever replaying an already-started graph."""

    from ghostcursor.task_runtime import TaskRunCode

    if getattr(result, "completed_node_ids", ()):
        return "terminal"
    if getattr(result, "code", None) is TaskRunCode.TARGET_NOT_RUNNING:
        return "target_not_running"
    if getattr(result, "code", None) is TaskRunCode.TARGET_CHOICE_REQUIRED:
        return "target_choice_required"
    return "terminal"


def execute_manager_task(request: TaskExecutionRequest) -> object:
    """Run reviewed graph data through the production-selected task authority."""

    from ghostcursor.task_runtime import execute_task_graph

    return execute_task_graph(
        request.graph,
        target_hwnd=request.target_hwnd,
        seconds_per_node=120.0,
    )


def project_snapshot(snapshot: SessionSnapshot) -> ManagerProjection:
    """Translate executor truth into labels without deriving new progress."""

    steps: list[ManagerStep] = []
    terminal_success = snapshot.status is SessionStatus.COMPLETED
    for number, instruction in enumerate(snapshot.plan_steps, start=1):
        if terminal_success or number < snapshot.current_step:
            state = "completed"
        elif number == snapshot.current_step and snapshot.current_step:
            state = "current"
        else:
            state = "pending"
        steps.append(ManagerStep(number, instruction, state))

    progress = (
        f"Step {snapshot.current_step} of {snapshot.total_steps}"
        if snapshot.total_steps and snapshot.current_step
        else f"{snapshot.total_steps} steps" if snapshot.total_steps else "No active plan"
    )
    details = "\n".join(
        line
        for line in (
            f"Plugin  {snapshot.plugin_id} {snapshot.plugin_version}"
            if snapshot.plugin_id
            else "",
            f"Intent  {snapshot.intent_id}" if snapshot.intent_id else "",
            f"Application  {snapshot.application}" if snapshot.application else "",
            f"Error  {snapshot.error_code}" if snapshot.error_code else "",
            "Processing  Local",
            (
                "Guidance\n"
                + "\n".join(
                    f"{value.name.replace('_', ' ').title()}  {value.value}"
                    for value in snapshot.guidance_values
                )
            )
            if snapshot.guidance_values
            else "",
        )
        if line
    )
    return ManagerProjection(
        status=_STATUS_LABELS[snapshot.status],
        goal=snapshot.goal,
        application=snapshot.application or "No application selected",
        progress=progress,
        instruction=snapshot.instruction or _terminal_instruction(snapshot.status),
        verification=snapshot.verification_state or _verification_label(snapshot.status),
        steps=tuple(steps),
        details=details,
        can_pause=snapshot.capabilities.can_pause,
        can_stop=snapshot.capabilities.can_stop,
        paused=snapshot.status is SessionStatus.PAUSED,
    )


def _terminal_instruction(status: SessionStatus) -> str:
    return {
        SessionStatus.COMPLETED: "The workflow reached its verified outcome.",
        SessionStatus.STOPPED: "The session ended without claiming completion.",
        SessionStatus.BLOCKED: "Authority changed or the workflow can no longer continue safely.",
        SessionStatus.FAILED: "The expected outcome was not verified.",
    }.get(status, "GhostCursor is preparing the next safe step.")


def _verification_label(status: SessionStatus) -> str:
    return {
        SessionStatus.VERIFYING: "Verifying the declared post-action state…",
        SessionStatus.COMPLETED: "Verified",
        SessionStatus.FAILED: "Not verified",
        SessionStatus.BLOCKED: "Verification unavailable",
    }.get(status, "Verification will remain visible here.")


def _set_font(hwnd: int) -> None:
    win32gui.SendMessage(
        hwnd,
        win32con.WM_SETFONT,
        win32gui.GetStockObject(DEFAULT_GUI_FONT),
        True,
    )


def _manager_wnd_proc(hwnd, msg, wparam, lparam):
    manager = _windows.get(hwnd)
    if msg == win32con.WM_COMMAND and manager is not None:
        manager._on_command(win32api.LOWORD(wparam), win32api.HIWORD(wparam))
        return 0
    if msg == win32con.WM_SIZE and manager is not None:
        manager._layout()
        return 0
    if msg == win32con.WM_ACTIVATE and manager is not None:
        if win32api.LOWORD(wparam) != win32con.WA_INACTIVE:
            manager.plugin_refresh_requested = True
        return 0
    if msg == win32con.WM_CTLCOLORSTATIC:
        win32gui.SetTextColor(wparam, COLOR_TEXT)
        win32gui.SetBkColor(wparam, COLOR_BACKGROUND)
        return _background_brush or 0
    if msg in (win32con.WM_CTLCOLOREDIT, win32con.WM_CTLCOLORLISTBOX):
        win32gui.SetTextColor(wparam, COLOR_TEXT)
        win32gui.SetBkColor(wparam, COLOR_SURFACE)
        return _surface_brush or 0
    if msg == win32con.WM_ERASEBKGND:
        if _background_brush:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            win32gui.FillRect(wparam, (left, top, right, bottom), _background_brush)
            return 1
    if msg == win32con.WM_CLOSE:
        if manager is not None:
            manager.request_stop_if_active()
        win32gui.DestroyWindow(hwnd)
        return 0
    if msg == win32con.WM_DESTROY:
        if manager is not None:
            manager.closed = True
        _windows.pop(hwnd, None)
        # Never PostQuitMessage: the executor shares this UI thread and may be
        # tearing down its overlay after the manager closes.
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class NativeManagerWindow:
    """A normal application window; never an execution or policy authority."""

    def __init__(self) -> None:
        global _background_brush, _surface_brush
        if _background_brush is None:
            _background_brush = win32gui.CreateSolidBrush(COLOR_BACKGROUND)
        if _surface_brush is None:
            _surface_brush = win32gui.CreateSolidBrush(COLOR_SURFACE)
        ensure_class(MANAGER_CLASS_NAME, _manager_wnd_proc, _background_brush)

        width = min(MANAGER_WIDTH, win32api.GetSystemMetrics(win32con.SM_CXSCREEN) - 80)
        height = min(MANAGER_HEIGHT, win32api.GetSystemMetrics(win32con.SM_CYSCREEN) - 80)
        x = max(24, (win32api.GetSystemMetrics(win32con.SM_CXSCREEN) - width) // 2)
        y = max(24, (win32api.GetSystemMetrics(win32con.SM_CYSCREEN) - height) // 2)
        self.hwnd = win32gui.CreateWindowEx(
            0,
            MANAGER_CLASS_NAME,
            MANAGER_TITLE,
            win32con.WS_OVERLAPPEDWINDOW,
            x,
            y,
            width,
            height,
            None,
            None,
            win32api.GetModuleHandle(None),
            None,
        )
        self.closed = False
        self.plugin_refresh_requested = True
        self._pending_request: (
            LaunchRequest | TaskProposalRequest | TaskExecutionRequest | None
        ) = None
        self._snapshot: SessionSnapshot | None = None
        self._target_candidates: tuple[object, ...] = ()
        self._target_choice_for = ""
        self._task_proposal: object | None = None
        self._mode = InteractionMode.TEACH
        self._plugins: tuple[PluginPresentation, ...] = ()
        self._plugin_rows: tuple[str, ...] = ()
        self._controls: dict[int, int] = {}
        _windows[self.hwnd] = self
        try:
            self._create_children()
            self._layout()
            self.show_idle()
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNORMAL)
            win32gui.UpdateWindow(self.hwnd)
        except BaseException:
            _windows.pop(self.hwnd, None)
            if win32gui.IsWindow(self.hwnd):
                win32gui.DestroyWindow(self.hwnd)
            raise

    def _child(self, class_name: str, text: str, style: int, control_id: int) -> int:
        child = win32gui.CreateWindowEx(
            0,
            class_name,
            text,
            win32con.WS_CHILD | win32con.WS_VISIBLE | style,
            0,
            0,
            10,
            10,
            self.hwnd,
            control_id,
            win32api.GetModuleHandle(None),
            None,
        )
        self._controls[control_id] = child
        _set_font(child)
        return child

    def _create_children(self) -> None:
        self._child("STATIC", "GhostCursor", win32con.SS_LEFT, ID_HEADER)
        self._child("STATIC", "Ready", win32con.SS_RIGHT, ID_STATUS)
        self._child("STATIC", "Mode", win32con.SS_LEFT, ID_MODE_LABEL)
        mode = self._child(
            "COMBOBOX",
            "",
            win32con.CBS_DROPDOWNLIST | win32con.WS_VSCROLL | win32con.WS_TABSTOP,
            ID_MODE,
        )
        for interaction_mode in MODE_ORDER:
            win32gui.SendMessage(
                mode, win32con.CB_ADDSTRING, 0, mode_label(interaction_mode)
            )
        win32gui.SendMessage(
            mode, win32con.CB_SETCURSEL, MODE_ORDER.index(self._mode), 0
        )
        self._child("STATIC", "Goal", win32con.SS_LEFT, ID_GOAL_LABEL)
        goal = self._child(
            "EDIT",
            "",
            win32con.WS_BORDER | win32con.ES_AUTOHSCROLL | win32con.WS_TABSTOP,
            ID_GOAL,
        )
        win32gui.SendMessage(goal, 0x1501, True, "What do you want to accomplish?")
        self._child("BUTTON", "Start", win32con.BS_PUSHBUTTON, ID_START)
        self._child("BUTTON", "Plan complex", win32con.BS_PUSHBUTTON, ID_COMPLEX)
        self._child("STATIC", mode_contract(self._mode).purpose, win32con.SS_LEFT, ID_MODE_NOTE)
        self._child("STATIC", "Plan", win32con.SS_LEFT, ID_PLAN_LABEL)
        self._child(
            "LISTBOX",
            "",
            win32con.WS_BORDER | win32con.WS_VSCROLL | win32con.LBS_NOTIFY,
            ID_TIMELINE,
        )
        self._child("STATIC", "No active plan", win32con.SS_LEFT, ID_PROGRESS)
        self._child("STATIC", "Current guidance", win32con.SS_LEFT, ID_GUIDANCE_LABEL)
        self._child("STATIC", "Start with a goal above.", win32con.SS_LEFT, ID_INSTRUCTION)
        self._child("STATIC", "Verification", win32con.SS_LEFT, ID_VERIFICATION_LABEL)
        self._child("STATIC", "No verification in progress.", win32con.SS_LEFT, ID_VERIFICATION)
        self._child("BUTTON", "Pause", win32con.BS_PUSHBUTTON, ID_PAUSE)
        self._child("BUTTON", "Stop", win32con.BS_PUSHBUTTON, ID_STOP)
        self._child("STATIC", "Installed plugins", win32con.SS_LEFT, ID_PLUGINS_LABEL)
        self._child(
            "LISTBOX",
            "",
            win32con.WS_BORDER | win32con.WS_VSCROLL,
            ID_PLUGINS,
        )
        self._child("STATIC", "Session details", win32con.SS_LEFT, ID_DETAILS_LABEL)
        self._child("STATIC", "Processing  Local", win32con.SS_LEFT, ID_DETAILS)
        self._child(
            "STATIC",
            "Local by default · no screenshots · diagnostics are user-created",
            win32con.SS_LEFT,
            ID_PRIVACY,
        )

    def _move(self, control_id: int, x: int, y: int, width: int, height: int) -> None:
        child = self._controls.get(control_id)
        if child:
            win32gui.MoveWindow(child, x, y, max(1, width), max(1, height), True)

    def _layout(self) -> None:
        if not hasattr(self, "_controls"):
            return
        _, _, width, height = win32gui.GetClientRect(self.hwnd)
        margin = 24
        gap = 16
        header_h = 32
        goal_h = 44
        right_w = max(220, width // 4)
        left_w = max(280, (width - 2 * margin - 2 * gap - right_w) // 2)
        middle_w = width - 2 * margin - 2 * gap - right_w - left_w
        body_y = 180
        footer_h = 34
        body_h = max(240, height - body_y - footer_h - margin)
        middle_x = margin + left_w + gap
        right_x = middle_x + middle_w + gap

        self._move(ID_HEADER, margin, 18, 360, header_h)
        self._move(ID_STATUS, width - margin - 280, 18, 280, header_h)
        action_w = 116
        mode_w = 150
        field_y = 78
        self._move(ID_MODE_LABEL, margin, 54, mode_w, 20)
        self._move(ID_MODE, margin, field_y, mode_w, 240)
        goal_x = margin + mode_w + 12
        self._move(ID_GOAL_LABEL, goal_x, 54, 160, 20)
        self._move(
            ID_GOAL,
            goal_x,
            field_y,
            width - goal_x - margin - 2 * action_w - 16,
            goal_h,
        )
        self._move(ID_START, width - margin - 2 * action_w - 8, field_y, action_w, goal_h)
        self._move(ID_COMPLEX, width - margin - action_w, field_y, action_w, goal_h)
        self._move(ID_MODE_NOTE, margin, 132, width - 2 * margin, 24)
        self._move(ID_PLAN_LABEL, margin, 160, left_w, 24)
        self._move(ID_TIMELINE, margin, body_y, left_w, body_h - 34)
        self._move(ID_PROGRESS, margin, body_y + body_h - 28, left_w, 24)
        self._move(ID_GUIDANCE_LABEL, middle_x, 160, middle_w, 24)
        self._move(ID_INSTRUCTION, middle_x, body_y, middle_w, 100)
        self._move(ID_VERIFICATION_LABEL, middle_x, body_y + 118, middle_w, 24)
        self._move(ID_VERIFICATION, middle_x, body_y + 150, middle_w, 84)
        self._move(ID_PAUSE, middle_x, body_y + body_h - 52, (middle_w - 8) // 2, 44)
        self._move(
            ID_STOP,
            middle_x + (middle_w - 8) // 2 + 8,
            body_y + body_h - 52,
            (middle_w - 8) // 2,
            44,
        )
        self._move(ID_PLUGINS_LABEL, right_x, 160, right_w, 24)
        self._move(ID_PLUGINS, right_x, body_y, right_w, 180)
        self._move(ID_DETAILS_LABEL, right_x, body_y + 198, right_w, 24)
        self._move(ID_DETAILS, right_x, body_y + 230, right_w, body_h - 230)
        self._move(ID_PRIVACY, margin, height - footer_h, width - 2 * margin, 24)

    def _select_mode(self, mode: InteractionMode) -> None:
        self._mode = mode
        win32gui.SendMessage(
            self._controls[ID_MODE], win32con.CB_SETCURSEL, MODE_ORDER.index(mode), 0
        )
        self._set(ID_MODE_NOTE, mode_contract(mode).purpose)

    def _render_mode_idle(self, *, update_content: bool = True) -> None:
        """Expose shipped modes and fail closed for roadmap-only modes."""

        contract = mode_contract(self._mode)
        self._set(ID_MODE_NOTE, contract.purpose)
        self._set(
            ID_START,
            "Start guidance" if self._mode is InteractionMode.TEACH else contract.label,
        )
        self._set(ID_COMPLEX, "Create plan")
        win32gui.EnableWindow(
            self._controls[ID_START], mode_can_start_guidance(self._mode)
        )
        win32gui.EnableWindow(
            self._controls[ID_COMPLEX], mode_can_propose_plan(self._mode)
        )
        if update_content and not contract.available:
            self._set(ID_STATUS, f"{contract.label} is a preview")
            self._set(ID_PROGRESS, "Not enabled in this trusted build")
            self._set(
                ID_INSTRUCTION,
                "This mode cannot create a plan, target, overlay, or action yet.",
            )
            self._set(
                ID_VERIFICATION,
                "A reviewed runtime capability is required before this mode can start.",
            )
        elif update_content and self._mode is InteractionMode.PLAN:
            self._set(
                ID_INSTRUCTION,
                "Choose one enabled plugin, then create a complete plan for review.",
            )
            self._set(
                ID_VERIFICATION,
                "Planning is inert. A separate Start plan action is required.",
            )

    def _on_command(self, control_id: int, _notification: int = 0) -> None:
        if control_id == ID_MODE:
            if self._snapshot is not None or self._task_proposal is not None:
                win32gui.SendMessage(
                    self._controls[ID_MODE],
                    win32con.CB_SETCURSEL,
                    MODE_ORDER.index(self._mode),
                    0,
                )
                return
            selected = win32gui.SendMessage(
                self._controls[ID_MODE], win32con.CB_GETCURSEL, 0, 0
            )
            if selected != win32con.CB_ERR and selected < len(MODE_ORDER):
                self._select_mode(MODE_ORDER[selected])
                self.show_idle()
            return
        if control_id == ID_START:
            if not mode_can_start_guidance(self._mode):
                self._set(ID_STATUS, "Select Teach to start guidance")
                return
            goal = win32gui.GetWindowText(self._controls[ID_GOAL]).strip()
            if not goal:
                self._set(ID_STATUS, "Enter a goal first")
                return
            target_hwnd = None
            if self._target_candidates and self._target_choice_for == "simple":
                selected = win32gui.SendMessage(
                    self._controls[ID_TIMELINE], win32con.LB_GETCURSEL, 0, 0
                )
                if selected == win32con.LB_ERR:
                    self._set(ID_STATUS, "Choose one window")
                    return
                target_hwnd = int(getattr(self._target_candidates[selected], "hwnd"))
            self._task_proposal = None
            self._pending_request = LaunchRequest(goal, target_hwnd)
            win32gui.EnableWindow(self._controls[ID_START], False)
            win32gui.EnableWindow(self._controls[ID_COMPLEX], False)
            win32gui.EnableWindow(self._controls[ID_MODE], False)
        elif control_id == ID_COMPLEX:
            if not mode_can_propose_plan(self._mode):
                self._set(ID_STATUS, "Select Plan to create a task plan")
                return
            goal = win32gui.GetWindowText(self._controls[ID_GOAL]).strip()
            if not goal:
                self._set(ID_STATUS, "Enter a goal first")
                return
            if self._task_proposal is not None:
                target_hwnd = None
                if self._target_candidates and self._target_choice_for == "complex":
                    selected = win32gui.SendMessage(
                        self._controls[ID_TIMELINE], win32con.LB_GETCURSEL, 0, 0
                    )
                    if selected == win32con.LB_ERR:
                        self._set(ID_STATUS, "Choose one window")
                        return
                    target_hwnd = int(getattr(self._target_candidates[selected], "hwnd"))
                self._pending_request = TaskExecutionRequest(
                    goal,
                    getattr(self._task_proposal, "graph"),
                    target_hwnd,
                )
            else:
                selected = win32gui.SendMessage(
                    self._controls[ID_PLUGINS], win32con.LB_GETCURSEL, 0, 0
                )
                if selected == win32con.LB_ERR or selected >= len(self._plugins):
                    self._set(ID_STATUS, "Choose one enabled plugin")
                    return
                plugin = self._plugins[selected]
                if plugin.state != "enabled_compatible" or not plugin.has_capabilities:
                    self._set(ID_STATUS, "Selected plugin has no active capabilities")
                    return
                self._pending_request = TaskProposalRequest(goal, plugin.plugin_id)
            win32gui.EnableWindow(self._controls[ID_START], False)
            win32gui.EnableWindow(self._controls[ID_COMPLEX], False)
            win32gui.EnableWindow(self._controls[ID_MODE], False)
        elif control_id == ID_PAUSE and self._snapshot is not None:
            if self._snapshot.capabilities.can_pause:
                session_commands.request(
                    self._snapshot.session_id, SessionCommand.TOGGLE_PAUSE
                )
        elif control_id == ID_STOP:
            self.request_stop_if_active()

    def request_stop_if_active(self) -> None:
        if self._snapshot is not None and self._snapshot.capabilities.can_stop:
            session_commands.request(self._snapshot.session_id, SessionCommand.STOP)

    def _set(self, control_id: int, text: str) -> None:
        child = self._controls.get(control_id)
        if child:
            win32gui.SetWindowText(child, text)

    def _replace_list(self, control_id: int, values: tuple[str, ...]) -> None:
        child = self._controls[control_id]
        win32gui.SendMessage(child, win32con.LB_RESETCONTENT, 0, 0)
        for value in values:
            win32gui.SendMessage(child, win32con.LB_ADDSTRING, 0, value)

    def render_snapshot(self, snapshot: SessionSnapshot) -> None:
        if self.closed or not win32gui.IsWindow(self.hwnd):
            return
        self._snapshot = snapshot
        self._target_candidates = ()
        self._target_choice_for = ""
        self._task_proposal = None
        projection = project_snapshot(snapshot)
        self._set(
            ID_HEADER,
            f"GhostCursor · {projection.application}"
            if snapshot.application
            else "GhostCursor",
        )
        self._set(ID_GOAL, projection.goal)
        self._set(ID_STATUS, projection.status)
        self._set(ID_PROGRESS, projection.progress)
        self._set(ID_INSTRUCTION, projection.instruction)
        self._set(ID_VERIFICATION, projection.verification)
        self._set(ID_DETAILS, projection.details)
        self._set(ID_PAUSE, "Resume" if projection.paused else "Pause")
        self._set(ID_START, "Start")
        self._set(ID_COMPLEX, "Plan complex")
        self._replace_list(
            ID_TIMELINE,
            tuple(
                f"{'✓' if step.state == 'completed' else '→' if step.state == 'current' else '○'}  "
                f"{step.number}. {step.instruction}"
                for step in projection.steps
            ),
        )
        win32gui.EnableWindow(self._controls[ID_PAUSE], projection.can_pause)
        win32gui.EnableWindow(self._controls[ID_STOP], projection.can_stop)
        terminal = snapshot.status in {
            SessionStatus.COMPLETED,
            SessionStatus.STOPPED,
            SessionStatus.BLOCKED,
            SessionStatus.FAILED,
        }
        win32gui.EnableWindow(self._controls[ID_START], terminal)
        win32gui.EnableWindow(self._controls[ID_COMPLEX], terminal)
        win32gui.EnableWindow(self._controls[ID_GOAL], terminal)
        win32gui.EnableWindow(self._controls[ID_MODE], terminal)
        if terminal:
            self._render_mode_idle(update_content=False)

    def show_idle(self) -> None:
        self._snapshot = None
        self._target_candidates = ()
        self._target_choice_for = ""
        self._task_proposal = None
        self._set(ID_HEADER, "GhostCursor")
        self._set(ID_STATUS, "Ready")
        self._set(ID_PROGRESS, "No active plan")
        self._set(ID_INSTRUCTION, "Describe a task to begin guided, verified work.")
        self._set(ID_VERIFICATION, "Verification will remain visible while you work.")
        self._replace_list(ID_TIMELINE, ())
        win32gui.EnableWindow(self._controls[ID_GOAL], True)
        win32gui.EnableWindow(self._controls[ID_MODE], True)
        win32gui.EnableWindow(self._controls[ID_PAUSE], False)
        win32gui.EnableWindow(self._controls[ID_STOP], False)
        self._render_mode_idle()

    def show_understanding(self, goal: str) -> None:
        self._target_candidates = ()
        self._target_choice_for = ""
        self._set(ID_STATUS, _STATUS_LABELS[SessionStatus.UNDERSTANDING])
        self._set(ID_PROGRESS, "Checking enabled plugin capabilities")
        self._set(ID_INSTRUCTION, goal)
        self._set(ID_VERIFICATION, "Nothing will execute before authorization.")
        self._set(ID_START, "Start")
        self._set(ID_COMPLEX, "Plan complex")
        self._replace_list(ID_TIMELINE, ("…  Understanding the goal",))
        win32gui.EnableWindow(self._controls[ID_GOAL], False)
        win32gui.EnableWindow(self._controls[ID_MODE], False)

    def show_unavailable(self, goal: str, explanation: str) -> None:
        self._target_candidates = ()
        self._target_choice_for = ""
        self._task_proposal = None
        self._set(ID_STATUS, "Unsupported or unavailable")
        self._set(ID_PROGRESS, "No executable plan")
        self._set(ID_INSTRUCTION, explanation)
        self._set(ID_VERIFICATION, "No target, selector, or overlay was created.")
        self._set(ID_START, "Start")
        self._set(ID_COMPLEX, "Plan complex")
        self._replace_list(ID_TIMELINE, ())
        win32gui.EnableWindow(self._controls[ID_START], True)
        win32gui.EnableWindow(self._controls[ID_COMPLEX], True)
        win32gui.EnableWindow(self._controls[ID_GOAL], True)
        win32gui.EnableWindow(self._controls[ID_MODE], True)
        self._render_mode_idle(update_content=False)

    def show_target_not_running(self, goal: str, explanation: str) -> None:
        self._target_candidates = ()
        self._target_choice_for = ""
        complex_retry = self._task_proposal is not None
        self._set(ID_STATUS, _STATUS_LABELS[SessionStatus.TARGET_NOT_RUNNING])
        self._set(ID_PROGRESS, "Start the application, then retry")
        self._set(ID_INSTRUCTION, explanation)
        self._set(ID_START, "Start" if complex_retry else "Retry")
        self._set(ID_COMPLEX, "Retry plan" if complex_retry else "Plan complex")
        win32gui.EnableWindow(self._controls[ID_START], not complex_retry)
        win32gui.EnableWindow(self._controls[ID_COMPLEX], complex_retry)
        win32gui.EnableWindow(self._controls[ID_GOAL], not complex_retry)
        win32gui.EnableWindow(self._controls[ID_MODE], False)

    def show_target_choices(self, goal: str, candidates: tuple[object, ...]) -> None:
        self._select_mode(InteractionMode.TEACH)
        self._target_candidates = candidates
        self._target_choice_for = "simple"
        self._set(ID_STATUS, _STATUS_LABELS[SessionStatus.TARGET_CHOICE_REQUIRED])
        self._set(ID_PROGRESS, f"{len(candidates)} trusted windows match")
        self._set(ID_INSTRUCTION, "Choose the exact window. GhostCursor will revalidate it before launch.")
        self._replace_list(
            ID_TIMELINE,
            tuple(
                f"[{candidate.hwnd}] {candidate.title} — "
                f"{candidate.app.executable_name} {candidate.app.version}"
                for candidate in candidates
            ),
        )
        self._set(ID_START, "Use window")
        win32gui.EnableWindow(self._controls[ID_START], True)
        win32gui.EnableWindow(self._controls[ID_COMPLEX], False)
        win32gui.EnableWindow(self._controls[ID_GOAL], False)
        win32gui.EnableWindow(self._controls[ID_MODE], False)

    def show_task_proposal(self, goal: str, proposal: object) -> None:
        """Present the entire validated graph; a second action must start it."""

        self._snapshot = None
        self._select_mode(InteractionMode.PLAN)
        self._target_candidates = ()
        self._target_choice_for = ""
        self._task_proposal = proposal
        rows = task_preview_rows(proposal)
        self._set(ID_STATUS, _STATUS_LABELS[SessionStatus.READY_TO_START])
        self._set(ID_PROGRESS, f"{len(rows)} validated steps")
        self._set(ID_INSTRUCTION, getattr(proposal, "summary"))
        self._set(ID_VERIFICATION, "Review every step. Nothing has executed yet.")
        self._replace_list(ID_TIMELINE, rows)
        self._set(ID_START, "Start")
        self._set(ID_COMPLEX, "Start plan")
        win32gui.EnableWindow(self._controls[ID_START], False)
        win32gui.EnableWindow(self._controls[ID_COMPLEX], True)
        win32gui.EnableWindow(self._controls[ID_GOAL], False)
        win32gui.EnableWindow(self._controls[ID_MODE], False)

    def show_task_target_choices(self, candidates: tuple[object, ...]) -> None:
        """Keep the reviewed graph while the operator selects its exact HWND."""

        if self._task_proposal is None:
            raise RuntimeError("task target choice requires a reviewed proposal")
        self._target_candidates = candidates
        self._target_choice_for = "complex"
        self._set(ID_STATUS, _STATUS_LABELS[SessionStatus.TARGET_CHOICE_REQUIRED])
        self._set(ID_PROGRESS, f"{len(candidates)} trusted windows match")
        self._set(ID_INSTRUCTION, "Choose the exact window for this reviewed plan.")
        self._replace_list(
            ID_TIMELINE,
            tuple(
                f"[{candidate.hwnd}] {candidate.title} — "
                f"{candidate.app.executable_name} {candidate.app.version}"
                for candidate in candidates
            ),
        )
        self._set(ID_COMPLEX, "Use window")
        win32gui.EnableWindow(self._controls[ID_START], False)
        win32gui.EnableWindow(self._controls[ID_COMPLEX], True)
        win32gui.EnableWindow(self._controls[ID_MODE], False)

    def show_task_result(self, result: object) -> None:
        """Render one graph-level outcome without inventing node progress."""

        self._target_candidates = ()
        self._target_choice_for = ""
        completed = bool(getattr(result, "completed", False))
        code = getattr(getattr(result, "code", None), "value", "task_failed")
        self._set(ID_STATUS, "Goal completed" if completed else "Plan stopped safely")
        self._set(ID_PROGRESS, code)
        self._set(ID_INSTRUCTION, getattr(result, "detail", "Task plan ended"))
        self._set(
            ID_VERIFICATION,
            "Every step reached its declared outcome." if completed
            else "No completion is claimed for the failed step.",
        )
        self._set(ID_START, "Start")
        self._set(ID_COMPLEX, "Plan complex")
        self._task_proposal = None
        win32gui.EnableWindow(self._controls[ID_START], True)
        win32gui.EnableWindow(self._controls[ID_COMPLEX], True)
        win32gui.EnableWindow(self._controls[ID_GOAL], True)
        win32gui.EnableWindow(self._controls[ID_MODE], True)
        self._render_mode_idle(update_content=False)

    def set_plugins(self, plugins: tuple[PluginPresentation, ...]) -> None:
        rows = tuple(
            f"{plugin.plugin_id} {plugin.version} — {plugin.state} — "
            f"{plugin.compatibility}"
            for plugin in plugins
        ) or ("No plugins installed",)
        self._plugins = plugins
        self._plugin_rows = rows
        self._replace_list(ID_PLUGINS, rows)
        self.plugin_refresh_requested = False

    def take_request(
        self,
    ) -> LaunchRequest | TaskProposalRequest | TaskExecutionRequest | None:
        request = self._pending_request
        self._pending_request = None
        return request

    def take_launch_request(self) -> LaunchRequest | None:
        """Compatibility accessor for the simple-goal native test boundary."""

        request = self.take_request()
        return request if isinstance(request, LaunchRequest) else None

    def dispose(self) -> None:
        if win32gui.IsWindow(self.hwnd):
            win32gui.DestroyWindow(self.hwnd)
        pump_messages_nonblocking()


def plugin_presentations() -> tuple[PluginPresentation, ...]:
    """Read status from PluginStore; never reimplement lifecycle policy."""

    from ghostcursor.plugins.platform import production_store

    store = production_store()
    installed = store.list_installed()
    try:
        capability_plugins = frozenset(store.load_composition_context().registries)
    except Exception:
        capability_plugins = frozenset()
    return tuple(
        PluginPresentation(
            plugin_id=plugin.plugin_id,
            version=plugin.version,
            state=plugin.state.value,
            compatibility=plugin.compatibility.reason,
            has_capabilities=plugin.plugin_id in capability_plugins,
        )
        for plugin in installed
    )


class _PlanningWorker:
    def __init__(self) -> None:
        self._result: queue.Queue[PlanningResult] = queue.Queue(maxsize=1)
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, request: LaunchRequest | TaskProposalRequest) -> None:
        if self.running:
            raise RuntimeError("planning is already running")

        def plan() -> None:
            try:
                if isinstance(request, TaskProposalRequest):
                    from ghostcursor.task_planner import propose_task_graph

                    result = propose_task_graph(request.goal, request.plugin_id)
                else:
                    from ghostcursor.reasoning.planner import plan_compiled_goal

                    result = plan_compiled_goal(
                        request.goal,
                        target_hwnd=request.target_hwnd,
                    )
                self._result.put(PlanningResult(request, result, None))
            except Exception as exc:
                self._result.put(PlanningResult(request, None, exc))

        self._thread = threading.Thread(target=plan, name="GhostCursorPlanner", daemon=True)
        self._thread.start()

    def take(self) -> PlanningResult | None:
        try:
            result = self._result.get_nowait()
        except queue.Empty:
            return None
        self._thread = None
        return result


def launch_manager() -> int:
    """Run the pilot-facing manager and tours in one native UI process."""

    from ghostcursor.run import run_tour_for_workflow

    manager = NativeManagerWindow()
    planning = _PlanningWorker()
    unsubscribe = session_events.subscribe(manager.render_snapshot)
    try:
        while win32gui.IsWindow(manager.hwnd):
            pump_messages_nonblocking()
            if manager.plugin_refresh_requested:
                try:
                    manager.set_plugins(plugin_presentations())
                except Exception as exc:
                    manager.set_plugins(())
                    manager._set(ID_STATUS, f"Plugin status unavailable: {type(exc).__name__}")

            request = manager.take_request()
            if isinstance(request, TaskExecutionRequest):
                manager._set(ID_STATUS, _STATUS_LABELS[SessionStatus.PLAN_VALIDATING])
                manager._set(ID_VERIFICATION, "Revalidating the whole graph before step 1.")
                result = execute_manager_task(request)
                action = task_result_action(result)
                if action == "target_not_running":
                    manager.show_target_not_running(request.goal, result.detail)
                elif action == "target_choice_required":
                    manager.show_task_target_choices(result.target_candidates)
                else:
                    manager.show_task_result(result)
                manager.plugin_refresh_requested = True
            elif request is not None and not planning.running:
                manager.show_understanding(request.goal)
                planning.start(request)

            planned = planning.take()
            if planned is not None:
                result, error = planned.result, planned.error
                if error is not None:
                    manager.show_unavailable(
                        planned.request.goal,
                        f"Planning failed: {type(error).__name__}: {error}",
                    )
                elif isinstance(planned.request, TaskProposalRequest):
                    manager.show_task_proposal(planned.request.goal, result)
                elif getattr(result, "plan", None) is not None:
                    run_tour_for_workflow(result.plan, seconds=120.0)
                    manager.plugin_refresh_requested = True
                elif getattr(result, "target_state", None) == "target_not_running":
                    manager.show_target_not_running("", result.explanation)
                elif getattr(result, "target_state", None) == "target_choice_required":
                    manager.show_target_choices("", result.target_candidates)
                else:
                    manager.show_unavailable("", result.explanation)
            time.sleep(0.02)
    finally:
        unsubscribe()
        manager.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(launch_manager())
