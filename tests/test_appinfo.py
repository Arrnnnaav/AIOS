import os
import sys

import pytest
import win32gui
import win32process

from ghostcursor.perception.appinfo import (
    _appx_version,
    _exe_path_for_pid,
    _file_version,
    app_info_for_window,
    parse_version,
)
from tests.uia_app import SyntheticApp


def test_parse_version_reads_dotted_numbers():
    assert parse_version("151.0.7922.110") == (151, 0, 7922, 110)
    assert parse_version("1.2") == (1, 2)


def test_parse_version_rejects_unparseable():
    assert parse_version("unknown") is None
    assert parse_version("") is None
    assert parse_version("1.2.beta") is None


def test_app_info_for_a_live_window():
    with SyntheticApp() as app:
        info = app_info_for_window(f".*{app.title}.*")
    assert info is not None
    # the synthetic app is hosted by python.exe, a plain Win32 binary
    assert info.kind == "win32"
    assert info.exe_path.lower().endswith(".exe")
    assert info.app_id == os.path.basename(sys.executable).lower()
    assert parse_version(info.version) is not None, f"got {info.version!r}"


def test_app_info_is_none_when_no_window_matches():
    assert app_info_for_window(".*NoSuchWindowAnywhere12345.*") is None


def test_app_info_for_a_store_app_prefers_appx_version():
    """Test that Store apps return the Appx package version, not the exe VERSIONINFO.

    This is the critical path that distinguishes Store apps from Win32 apps.
    The Appx package version is authoritative for Store apps and may differ
    significantly from the exe's VERSIONINFO (e.g., Terminal reports
    1.24.2607.10001 in VERSIONINFO but 1.24.11911.0 in the package).
    """
    # Discover a Store app by enumerating all visible windows and finding one
    # whose process runs from WindowsApps.
    found_appx: list[tuple[str, str]] = []  # (exe_path, window_title)

    def _collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            exe_path = _exe_path_for_pid(pid)
            if exe_path and "WindowsApps" in exe_path:
                title = win32gui.GetWindowText(hwnd)
                found_appx.append((exe_path, title))
        except Exception:
            pass

    win32gui.EnumWindows(_collect, None)

    if not found_appx:
        pytest.skip("No Store app window found in the environment")

    exe_path, title = found_appx[0]
    info = app_info_for_window(f".*{title}.*")
    assert info is not None
    assert info.kind == "appx"
    assert parse_version(info.version) is not None

    # The critical assertion: version must come from the Appx package,
    # not the exe's VERSIONINFO. They legitimately differ for Store apps.
    file_version = _file_version(exe_path)
    appx_version = _appx_version(exe_path)
    assert info.version == appx_version, (
        f"expected Appx package version {appx_version!r}, "
        f"but got {info.version!r} (exe VERSIONINFO is {file_version!r})"
    )


def test_a_minimized_window_is_not_used_for_app_identity():
    """App identity and grounding must agree on which window they mean.

    perception.uia's enumeration excludes minimized and off-screen windows,
    because a hint cannot be drawn on one. appinfo's copy did not, so a
    minimized window could supply the app identity that observations are
    persisted under while grounding refused that same window. Both now share
    one enumeration helper, so they cannot drift apart again.
    """
    import win32con
    import win32gui

    from ghostcursor.perception.appinfo import app_info_for_window
    from tests.uia_app import SyntheticApp

    with SyntheticApp(title="GhostCursorMinimizedProbe") as app:
        title_re = f".*{app.title}.*"
        assert app_info_for_window(title_re) is not None, (
            "visible window should resolve"
        )

        win32gui.ShowWindow(app.hwnd, win32con.SW_MINIMIZE)
        app.pump()
        try:
            assert app_info_for_window(title_re) is None, (
                "a minimized window supplied app identity; grounding would "
                "have refused that same window"
            )
        finally:
            win32gui.ShowWindow(app.hwnd, win32con.SW_RESTORE)
            app.pump()


def test_a_package_name_with_shell_metacharacters_is_refused():
    """A path-derived value must not reach a PowerShell -Command string.

    WindowsApps is system-protected, so this is defence rather than a live
    hole — but the guard is what makes that a property of the code instead of
    a property of the filesystem.
    """
    from ghostcursor.perception import appinfo

    # Asserting only that the result is UNKNOWN would be vacuous: with the
    # guard removed, PowerShell runs the mangled name, produces no output, and
    # the `or UNKNOWN` fallback returns the very same answer. The first
    # version of this test did exactly that and survived deleting the guard.
    # The property worth pinning is that the shell is never reached at all.
    calls = []

    def _record(*args, **kwargs):
        calls.append(args)
        raise AssertionError("subprocess.run must not be reached for a hostile name")

    original = appinfo.subprocess.run
    appinfo.subprocess.run = _record
    try:
        hostile = (
            r"C:\Program Files\WindowsApps\Bad; Remove-Item C:\_1.0_x64__abc\app.exe"
        )
        assert appinfo._appx_version(hostile) == appinfo.UNKNOWN
    finally:
        appinfo.subprocess.run = original

    assert calls == [], "a path-derived name reached the shell"


def test_a_missing_powershell_is_reported_not_silently_unknown(capsys, monkeypatch):
    """A broken environment must be distinguishable from an app with no version."""
    import subprocess as subprocess_module

    from ghostcursor.perception import appinfo

    appinfo._warned.clear()

    def _explode(*args, **kwargs):
        raise FileNotFoundError("powershell.exe not found")

    monkeypatch.setattr(subprocess_module, "run", _explode)
    monkeypatch.setattr(appinfo.subprocess, "run", _explode)

    path = r"C:\Program Files\WindowsApps\Microsoft.Something_1.0_x64__abc\app.exe"
    assert appinfo._appx_version(path) == appinfo.UNKNOWN
    assert "could not read the Store package version" in capsys.readouterr().out
