"""Small deterministic Win32 app used by the export recipe and integration tests."""
from __future__ import annotations

import win32api
import win32con
import win32gui

APP_TITLE = "Synthetic Export"
EXPORT_ID = 1005
WRONG_ID = 1006
STATUS_ID = 1007
CLASS_NAME = "GhostCursorSyntheticExport"


def _proc(hwnd, msg, wparam, lparam):
    if msg == win32con.WM_COMMAND:
        control_id = win32api.LOWORD(wparam)
        if control_id == EXPORT_ID:
            win32gui.SetWindowText(win32gui.GetDlgItem(hwnd, STATUS_ID), "Export finished: table.csv")
        elif control_id == WRONG_ID:
            win32gui.SetWindowText(win32gui.GetDlgItem(hwnd, STATUS_ID), "Wrong control — nothing exported")
        return 0
    if msg == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def create_window() -> int:
    instance = win32api.GetModuleHandle(None)
    wc = win32gui.WNDCLASS()
    wc.hInstance = instance
    wc.lpszClassName = CLASS_NAME
    wc.lpfnWndProc = _proc
    wc.hbrBackground = win32gui.GetStockObject(win32con.WHITE_BRUSH)
    try:
        win32gui.RegisterClass(wc)
    except win32gui.error:
        pass
    hwnd = win32gui.CreateWindowEx(0, CLASS_NAME, APP_TITLE, win32con.WS_OVERLAPPEDWINDOW,
                                   300, 200, 520, 260, 0, 0, instance, None)
    style = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON
    win32gui.CreateWindowEx(0, "BUTTON", "Export", style, 30, 35, 180, 42, hwnd, EXPORT_ID, instance, None)
    win32gui.CreateWindowEx(0, "BUTTON", "Wrong control", style, 230, 35, 180, 42, hwnd, WRONG_ID, instance, None)
    win32gui.CreateWindowEx(0, "STATIC", "Ready to export", win32con.WS_CHILD | win32con.WS_VISIBLE,
                            30, 120, 400, 32, hwnd, STATUS_ID, instance, None)
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    win32gui.UpdateWindow(hwnd)
    return hwnd


def main() -> int:
    create_window()
    while win32gui.PumpWaitingMessages() != 1:
        win32api.Sleep(20)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
