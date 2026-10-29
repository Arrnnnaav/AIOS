"""Every name the shipped code uses is defined (ruff F821). The console's
REPL is not unit-tested, so an import dropped there (telemetry, _preview)
only showed as a NameError when the user ran the command."""

import shutil
import subprocess
import sys

import pytest


def test_no_undefined_names():
    if shutil.which("ruff") is None and subprocess.run(
        [sys.executable, "-m", "ruff", "--version"], capture_output=True
    ).returncode:
        pytest.skip("ruff is not installed")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "ghostcursor", "tools",
         "--select", "F821", "--no-cache", "--output-format", "concise"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout
