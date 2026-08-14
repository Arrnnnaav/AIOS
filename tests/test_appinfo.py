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
