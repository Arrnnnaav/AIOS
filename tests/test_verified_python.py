from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys


BOOTSTRAP = Path(__file__).resolve().parents[1] / "ghostcursor" / "verified_python.py"


def _run(path, digest, *arguments):
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(BOOTSTRAP),
            "--sha256",
            digest,
            str(path),
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_verified_python_executes_the_exact_approved_bytes(tmp_path):
    source = tmp_path / "payload.py"
    source.write_text(
        "import sys\n"
        "print(__ghostcursor_verified_sha256__)\n"
        "print('|'.join(sys.argv))\n",
        encoding="utf-8",
        newline="\n",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    completed = _run(source, digest, "--child", "value")

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [
        digest,
        f"{source.resolve()}|--child|value",
    ]


def test_changed_payload_bytes_never_execute_top_level_code(tmp_path):
    source = tmp_path / "payload.py"
    marker = tmp_path / "executed.txt"
    approved = b"pass\n"
    digest = hashlib.sha256(approved).hexdigest()
    source.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
        newline="\n",
    )

    completed = _run(source, digest)

    assert completed.returncode != 0
    assert "changed before execution" in completed.stderr
    assert not marker.exists()


def test_an_invalid_expected_digest_refuses_before_reading_the_payload(tmp_path):
    missing = tmp_path / "does-not-exist.py"

    completed = _run(missing, "not-a-digest")

    assert completed.returncode != 0
    assert "digest is invalid" in completed.stderr
    assert "does-not-exist" not in completed.stderr


def test_a_mutable_sibling_module_is_not_importable_after_main_byte_verification(
    tmp_path,
):
    source = tmp_path / "payload.py"
    helper = tmp_path / "helper.py"
    marker = tmp_path / "helper-ran.txt"
    source.write_text("import helper\n", encoding="utf-8", newline="\n")
    helper.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
        newline="\n",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    completed = _run(source, digest)

    assert completed.returncode != 0
    assert not marker.exists()


def test_bootstrap_refuses_when_system_site_startup_was_not_disabled(tmp_path):
    source = tmp_path / "payload.py"
    marker = tmp_path / "payload-ran.txt"
    source.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
        newline="\n",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(BOOTSTRAP),
            "--sha256",
            digest,
            str(source),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "requires -I -S" in completed.stderr
    assert not marker.exists()


def test_pywin32_directories_are_found_in_the_system_site_too(tmp_path):
    """CI 2026-11-11: pywin32 installed system-wide (not --user) left the
    adapter child unable to import win32api, because only the user site's
    PyWin32 directories were added under -S."""
    from ghostcursor.verified_python import _dependency_paths

    system, user, missing = tmp_path / "system", tmp_path / "user", tmp_path / "gone"
    for d in (system / "win32" / "lib", system / "Pythonwin", system / "pywin32_system32", user):
        d.mkdir(parents=True)
    paths, dlls = _dependency_paths([system, system, user, missing])
    assert paths == [system, system / "win32", system / "win32" / "lib", system / "Pythonwin", user]
    assert dlls == [system / "pywin32_system32"]


def test_payload_folders_never_join_the_dependency_paths(tmp_path):
    from ghostcursor.verified_python import _dependency_paths

    site_dir = tmp_path / "site"
    (site_dir / "win32").mkdir(parents=True)
    (site_dir / "pywin32_system32").mkdir()
    paths, dlls = _dependency_paths(
        [site_dir], exclude=(site_dir / "win32", site_dir / "pywin32_system32")
    )
    assert paths == [site_dir] and dlls == []


def test_a_failed_dll_directory_closes_the_ones_already_added():
    import pytest

    from ghostcursor.verified_python import _add_dll_directories

    closed = []

    class Handle:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    def add(name):
        if name == "bad":
            raise OSError("no such directory")
        return Handle(name)

    assert [h.name for h in _add_dll_directories(["a", "b"], add)] == ["a", "b"]
    assert closed == []
    with pytest.raises(OSError):
        _add_dll_directories(["a", "b", "bad"], add)
    assert closed == ["a", "b"]
