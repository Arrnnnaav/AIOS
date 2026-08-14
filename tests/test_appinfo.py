import os
import sys

from ghostcursor.perception.appinfo import app_info_for_window, parse_version
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
