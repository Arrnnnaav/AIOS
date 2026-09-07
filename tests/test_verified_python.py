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
