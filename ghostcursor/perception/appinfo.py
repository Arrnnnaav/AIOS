"""Which application is this, and which version of it is running.

Needed because a learned AutomationId is only meaningful alongside the
version it was observed on (spec §9). Verified on this machine:

    HWND -> PID -> QueryFullProcessImageNameW -> exe path -> GetFileVersionInfo
        Chrome (Win32)    -> 151.0.7922.110
        Terminal (Store)  -> VERSIONINFO 1.24.2607.10001
                          -> Appx pkg   1.24.11911.0   <- authoritative, differs

For Store apps the package version is authoritative and the exe's VERSIONINFO
disagrees, so the WindowsApps branch is not optional.

Results are cached per (exe_path, mtime): the version of an installed binary
cannot change without the file changing, and the Appx lookup shells out.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
from dataclasses import dataclass

import win32api
import win32process

from ghostcursor.overlay import dpi  # noqa: F401  declares DPI awareness first
from ghostcursor.perception.uia import windows_matching

UNKNOWN = "unknown"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_cache: dict[tuple[str, float], str] = {}


@dataclass(frozen=True)
class AppInfo:
    app_id: str
    exe_path: str
    version: str
    kind: str  # "win32" | "appx"


def parse_version(text: str) -> tuple[int, ...] | None:
    """Dotted numeric version to a comparable tuple, or None if unparseable."""
    if not text or text == UNKNOWN:
        return None
    parts = text.split(".")
    if not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def _exe_path_for_pid(pid: int) -> str | None:
    handle = ctypes.windll.kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(32768)
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        )
        return buf.value if ok else None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


#: A package name is an identifier, not free text. Guarding it keeps a
#: path-derived value from reaching a PowerShell -Command string. WindowsApps
#: is system-protected so this is not currently exploitable; the guard costs a
#: line and removes the question.
_PACKAGE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _file_version(exe_path: str) -> str:
    """Version from the exe's VERSIONINFO resource, or UNKNOWN.

    Narrow catches on purpose: a file with no version resource is ordinary and
    yields UNKNOWN quietly, but anything else is a real failure and should not
    be indistinguishable from it.
    """
    try:
        info = win32api.GetFileVersionInfo(exe_path, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except (win32api.error, KeyError, OSError):
        return UNKNOWN


def _appx_version(exe_path: str) -> str:
    """Store apps carry the authoritative version in the package, not the exe."""
    match = re.search(r"WindowsApps\\([^\\]+)", exe_path)
    if not match:
        return UNKNOWN
    package_name = match.group(1).split("_")[0]
    if not _PACKAGE_NAME.match(package_name):
        return UNKNOWN

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-AppxPackage -Name {package_name}).Version",
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # A missing powershell.exe or a timeout is a real environment
        # problem, not "this app has no version" — say so once rather than
        # collapsing it into the same silent UNKNOWN.
        _warn_once(f"could not read the Store package version ({type(exc).__name__})")
        return UNKNOWN
    return result.stdout.strip() or UNKNOWN


_warned: set[str] = set()


def _warn_once(message: str) -> None:
    if message not in _warned:
        _warned.add(message)
        print(f"Ghost Cursor: {message}")


def _version_for(exe_path: str, kind: str) -> str:
    try:
        key = (exe_path, os.path.getmtime(exe_path))
    except OSError:
        key = (exe_path, 0.0)
    if key not in _cache:
        _cache[key] = (
            _appx_version(exe_path) if kind == "appx" else _file_version(exe_path)
        )
    return _cache[key]


def app_info_for_window(
    title_re: str, expected_app_id: str | None = None
) -> AppInfo | None:
    """Identify the application owning the first visible window matching
    title_re and, when supplied, the expected executable basename."""
    # Shared with grounding on purpose (see uia.windows_matching): a window
    # that grounding would refuse must not supply the app identity that
    # observations are persisted under.
    found = windows_matching(title_re)
    if not found:
        return None

    expected = os.path.basename(expected_app_id).casefold() if expected_app_id else None
    for hwnd in found:
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        exe_path = _exe_path_for_pid(pid)
        if not exe_path:
            continue
        app_id = os.path.basename(exe_path).casefold()
        if expected is not None and app_id != expected:
            continue

        kind = "appx" if "WindowsApps" in exe_path else "win32"
        return AppInfo(
            app_id=app_id,
            exe_path=exe_path,
            version=_version_for(exe_path, kind),
            kind=kind,
        )
    return None
