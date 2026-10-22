"""Shipping metadata a sellable release must carry: a single version string
support/telemetry/update-check can read, and a pinned dependency manifest so a
production build is reproducible. Cheap guards against regressing either.
"""

from __future__ import annotations

import re
from pathlib import Path

import ghostcursor

ROOT = Path(__file__).resolve().parents[1]

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def test_the_package_reports_a_semver_version():
    assert isinstance(ghostcursor.__version__, str)
    assert _SEMVER.match(ghostcursor.__version__), ghostcursor.__version__


def test_requirements_are_pinned_and_cover_the_runtime_deps():
    """Every runtime dep is pinned to an exact version (== ), not a floating
    range, so two builds of the same release install the same bytes."""

    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pins = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?==([0-9][\w.]*)", line)
        assert m, f"unpinned or malformed requirement: {line!r}"
        pins[m.group(1).casefold()] = m.group(2)

    # The deps the overlay, perception, trust and provider paths cannot run
    # without -- a dropped pin here is a broken production build.
    for required in ("pywin32", "pywinauto", "numpy", "cryptography", "ollama"):
        assert required.casefold() in pins, f"{required} missing from requirements.txt"
