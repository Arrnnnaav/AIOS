"""The user-level installer must keep the last complete build on update failure."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_installer_stages_updates_rolls_back_and_recovers(tmp_path):
    script = Path(__file__).resolve().parents[1] / "tools" / "Install-Orbyn.ps1"
    source = tmp_path / "build"
    source.mkdir()
    exe = source / "Orbyn.exe"
    install = tmp_path / "Programs" / "Orbyn"
    links = tmp_path / "links"
    links.mkdir()
    start = links / "start.lnk"
    desktop = links / "desktop.lnk"

    def run(*extra):
        return subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script),
             "-SourceDir", str(source), "-InstallDir", str(install),
             "-StartMenuLnk", str(start), "-DesktopLnk", str(desktop), *extra],
            capture_output=True, text=True, timeout=30,
        )

    exe.write_text("v1", encoding="utf-8")
    (source / "old.txt").write_text("old", encoding="utf-8")
    assert run().returncode == 0
    assert (install / "Orbyn.exe").read_text(encoding="utf-8") == "v1"
    assert start.exists() and desktop.exists()

    exe.write_text("v2", encoding="utf-8")
    (source / "old.txt").unlink()
    (source / "new.txt").write_text("new", encoding="utf-8")
    assert run().returncode == 0
    assert (install / "Orbyn.exe").read_text(encoding="utf-8") == "v2"
    assert (install / "new.txt").exists() and not (install / "old.txt").exists()
    assert (install / ".install-complete").exists()
    assert not (install.parent / "Orbyn.previous").exists()

    exe.write_text("v3", encoding="utf-8")
    bad_link = tmp_path / "missing" / "start.lnk"
    failed = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script),
         "-SourceDir", str(source), "-InstallDir", str(install),
         "-StartMenuLnk", str(bad_link), "-DesktopLnk", str(desktop)],
        capture_output=True, text=True, timeout=30,
    )
    assert failed.returncode != 0
    assert (install / "Orbyn.exe").read_text(encoding="utf-8") == "v2"
    assert not (install.parent / "Orbyn.previous").exists()

    # A crash after the new build completed keeps it and clears the old backup.
    (install.parent / "Orbyn.previous").mkdir()
    (install.parent / "Orbyn.previous" / "Orbyn.exe").write_text("v1", encoding="utf-8")
    exe.unlink()
    assert run().returncode != 0
    assert (install / "Orbyn.exe").read_text(encoding="utf-8") == "v2"
    assert not (install.parent / "Orbyn.previous").exists()

    # A crash while removing the failed new build must prefer the intact backup.
    (install / ".install-complete").unlink()
    install.rename(install.parent / "Orbyn.staging")
    (install.parent / "Orbyn.previous").mkdir()
    (install.parent / "Orbyn.previous" / "Orbyn.exe").write_text("v2", encoding="utf-8")
    (install.parent / "Orbyn.staging").rename(install)
    assert run().returncode != 0
    assert (install / "Orbyn.exe").read_text(encoding="utf-8") == "v2"
    assert not (install.parent / "Orbyn.previous").exists()

    install.rename(install.parent / "Orbyn.previous")  # interrupted after moving the old build
    assert run().returncode != 0
    assert (install / "Orbyn.exe").read_text(encoding="utf-8") == "v2"

    personal = tmp_path / "GhostCursor" / "kb.sqlite"
    personal.parent.mkdir()
    personal.write_text("personal data", encoding="utf-8")
    assert run("-Uninstall").returncode == 0
    assert not install.exists() and not start.exists() and not desktop.exists()
    assert personal.read_text(encoding="utf-8") == "personal data"
