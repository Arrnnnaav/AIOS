"""Reading which control currently has keyboard focus.

Wrong-action feedback needs to know that the user interacted with something,
and WHICH something. Focus is the right signal for that: it changes because a
user acted on a control, where the element set churns on its own -- VS Code's
element identity was measured fluctuating in steady state with no user action
at all (2026-08-19-cold-electron-probe-findings.md, section 3). A signal that
fires when the user did nothing is worse than no signal.

This module answers ONE question and knows nothing about steps, recipes or
grounding: which in-process AutomationId has focus right now, or "".
"""

from __future__ import annotations

import threading

#: The IUIAutomation instance, PER THREAD. This is not an optimisation.
#: UIA objects are apartment-bound (D021): one instance created on the UI
#: thread and then used from the perception worker gives confusing
#: intermittent failures rather than a clean error. threading.local() makes
#: "the object belongs to the thread that made it" structural instead of a
#: convention someone has to remember.
_local = threading.local()

_CLSID_CUIAutomation = "{ff48dba4-60ef-4201-aa87-54103eef594e}"


def _automation():
    existing = getattr(_local, "uia", None)
    if existing is not None:
        return existing
    import comtypes.client

    module = comtypes.client.GetModule("UIAutomationCore.dll")
    _local.uia = comtypes.client.CreateObject(
        _CLSID_CUIAutomation, interface=module.IUIAutomation
    )
    return _local.uia


def _process_id_for(hwnd: int) -> int:
    """Owning process of `hwnd`, or 0.

    A module-level function rather than an inline import so a test can
    substitute it without needing a real window AND a real foreground grab --
    see tests/test_focus.py on why real focus cannot be taken reliably.
    """
    try:
        import win32process

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return int(pid or 0)
    except Exception:
        return 0


def read_focused_automation_id(hwnd: int) -> str:
    """AutomationId of the focused control, if it is inside `hwnd`'s process.

    Returns "" for every case we cannot act on, and never raises:

    * focus is in another process -- the user alt-tabbed away, which is not a
      mis-click and must not be reported as one
    * the focused element has no AutomationId -- common in Chromium and
      Acrobat. We can see that focus moved but cannot name where, and naming
      is the whole point: never accuse without naming.
    * anything at all went wrong. The caller is the perception worker, whose
      product is the walk; focus is a nicety and must never cost an
      observation.
    """
    # Redundant with _process_id_for's own exception handling TODAY -- a bad
    # handle currently makes that call fail internally and return 0 anyway.
    # Kept deliberately (same reasoning as D030's provenance guard): that
    # redundancy is a coincidence of _process_id_for's current error
    # handling, not a property, and a future change there (raising instead
    # of swallowing, or a Windows build that answers for handle 0) would
    # make this guard load-bearing again with nothing left to notice its
    # absence. test_the_hwnd_guard_holds_even_if_the_process_lookup_succeeds
    # in tests/test_focus.py proves it still does something by forcing
    # _process_id_for to answer for a bogus handle.
    if hwnd <= 0:
        return ""
    try:
        target_pid = _process_id_for(hwnd)
        if not target_pid:
            return ""
        element = _automation().GetFocusedElement()
        if element is None or element.CurrentProcessId != target_pid:
            return ""
        return element.CurrentAutomationId or ""
    except Exception:
        return ""
