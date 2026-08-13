"""A real Win32 window with known AutomationIds, used as a grounding target.

Grounding tests need an application whose element identities we control
exactly. Using a real app (Notepad, Chrome) makes tests depend on that app's
version and UI language. This gives us both, deterministically: the same
control IDs under any locale, with different display names.

Win32 controls expose their integer control ID as the UIA AutomationId, which
is what makes rung 1 of the grounding ladder testable here.
"""

import win32api
import win32con
import win32gui

from ghostcursor.overlay import dpi  # noqa: F401  declares DPI awareness first

BTN_EXPORT = 1001
BTN_DELETE = 1002
BTN_CANCEL = 1003
EDIT_FILENAME = 1004
LBL_STATUS = 1005

LOCALIZED_NAMES = {
    "en-US": {
        BTN_EXPORT: "Export",
        BTN_DELETE: "Delete",
        BTN_CANCEL: "Cancel",
        LBL_STATUS: "Ready",
    },
    "hi-IN": {
        BTN_EXPORT: "निर्यात",
        BTN_DELETE: "हटाएं",
        BTN_CANCEL: "रद्द करें",
        LBL_STATUS: "तैयार",
    },
}

_LAYOUT = {
    BTN_EXPORT: (30, 40, 140, 34),
    BTN_DELETE: (30, 90, 140, 34),
    BTN_CANCEL: (30, 140, 140, 34),
    EDIT_FILENAME: (200, 40, 180, 28),
    LBL_STATUS: (200, 90, 180, 28),
}

_registered: set[str] = set()


class SyntheticApp:
    """Context manager owning a real top-level window and its child controls."""

    def __init__(self, title: str = "GhostCursorTestApp", locale: str = "en-US"):
        self.title = title
        self.locale = locale
        self.hwnd: int | None = None
        self._children: dict[int, int] = {}

    def __enter__(self) -> "SyntheticApp":
        h_instance = win32api.GetModuleHandle(None)
        class_name = f"GhostCursorSynthetic_{self.title}"

        if class_name not in _registered:
            wnd_class = win32gui.WNDCLASS()
            wnd_class.lpfnWndProc = win32gui.DefWindowProc
            wnd_class.hInstance = h_instance
            wnd_class.lpszClassName = class_name
            wnd_class.hbrBackground = win32gui.GetStockObject(win32con.WHITE_BRUSH)
            win32gui.RegisterClass(wnd_class)
            _registered.add(class_name)

        self.hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_TOOLWINDOW,
            class_name,
            self.title,
            win32con.WS_OVERLAPPEDWINDOW,
            200,
            200,
            420,
            260,
            None,
            None,
            h_instance,
            None,
        )

        names = LOCALIZED_NAMES[self.locale]
        for control_id, (x, y, w, h) in _LAYOUT.items():
            if control_id == EDIT_FILENAME:
                cls, style, text = "EDIT", win32con.WS_BORDER, ""
            elif control_id == LBL_STATUS:
                cls, style, text = "STATIC", 0, names[control_id]
            else:
                cls, style, text = "BUTTON", win32con.BS_PUSHBUTTON, names[control_id]

            self._children[control_id] = win32gui.CreateWindowEx(
                0,
                cls,
                text,
                win32con.WS_CHILD | win32con.WS_VISIBLE | style,
                x,
                y,
                w,
                h,
                self.hwnd,
                control_id,
                h_instance,
                None,
            )

        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.UpdateWindow(self.hwnd)
        self.pump()
        return self

    def __exit__(self, *exc) -> None:
        if self.hwnd:
            win32gui.DestroyWindow(self.hwnd)
            self.pump()
        self.hwnd = None

    def pump(self) -> None:
        win32gui.PumpWaitingMessages()

    def set_status(self, text: str) -> None:
        """Change the status label — how tests simulate the app reacting."""
        win32gui.SetWindowText(self._children[LBL_STATUS], text)
        self.pump()

    def hide_control(self, control_id: int) -> None:
        win32gui.ShowWindow(self._children[control_id], win32con.SW_HIDE)
        self.pump()

    def show_control(self, control_id: int) -> None:
        win32gui.ShowWindow(self._children[control_id], win32con.SW_SHOW)
        self.pump()

    def click_button(self, control_id: int) -> None:
        """Stand-in for 'the user clicked this'. Mutates only this test
        window's own state — never synthesises input to another application."""
        self.set_status(f"clicked:{control_id}")
