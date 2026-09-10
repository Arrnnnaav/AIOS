"""Every writer of a retained artifact emits LF, on every platform.

This root cause has now appeared six times: a CRLF working copy of a signed
payload (D125), a CRLF evidence artifact from the deck probe (D126), a `.pyc`
in a signed manifest (D127), an untracked file swept into a bundle (D130), and
`act_acceptance.py` opening its diagnostics file in text mode without
`newline=` (D132). Each instance was fixed; the class was not, because nothing
asserted the property across all writers at once.

Text mode on Windows translates "\\n" to "\\r\\n". Any file whose bytes are
hashed -- a payload, an evidence artifact, a campaign transcript -- then
reproduces only on the platform that wrote it, so a digest quoted in a document
is a fact about one machine rather than about the repository.

`act_acceptance.py` is the sharpest case: CLAUDE.md names it as the tool for the
instrumented acceptance campaign, so its output is exactly what a counted
campaign would retain.
"""

import ast
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Modules that write an artifact somebody later hashes or commits.
_WRITERS = (
    "ghostcursor/devtools/act_acceptance.py",
    "ghostcursor/devtools/act_campaign.py",
    "ghostcursor/devtools/act_live_node.py",
    "ghostcursor/devtools/act_deck_observation.py",
    "ghostcursor/devtools/uia_feasibility.py",
    "ghostcursor/evaluation/model_gate.py",
    "ghostcursor/act_staging.py",
    "ghostcursor/brief.py",
    "ghostcursor/reasoning/schema.py",
    "tools/render_add_slide_evidence.py",
    "tools/render_excel_plugin_evidence.py",
    "tools/render_open_extensions_evidence.py",
    "tools/render_acceptance_evidence.py",
    "tools/render_receipt_budget.py",
)


def _text_writes_without_newline(source: str):
    """Every `open(..., "w")` / `write_text(...)` that does not pin newline."""

    offenders = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in {"open", "write_text"}:
            continue
        keywords = {kw.arg for kw in node.keywords}
        if "newline" in keywords:
            continue
        if name == "open":
            modes = [
                a.value
                for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            modes += [
                kw.value.value
                for kw in node.keywords
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant)
            ]
            # Binary modes do no translation, and a read needs no pin.
            if not modes or all(
                "b" in m or "w" not in m and "a" not in m for m in modes
            ):
                continue
        offenders.append(f"line {node.lineno}: {name}(...)")
    return offenders


def test_the_writer_list_still_describes_real_files():
    """Non-vacuity: a renamed module would silently drop out of the check."""

    missing = [name for name in _WRITERS if not (ROOT / name).is_file()]
    assert not missing, missing
    assert len(_WRITERS) >= 10


@pytest.mark.parametrize("name", _WRITERS)
def test_every_artifact_writer_pins_its_newline(name):
    source = (ROOT / name).read_text(encoding="utf-8")

    offenders = _text_writes_without_newline(source)

    assert not offenders, f"{name} writes text without newline=:\n" + "\n".join(
        offenders
    )


def test_the_scan_catches_a_planted_unpinned_write():
    """A check that cannot fire proves nothing about the files it passed."""

    assert _text_writes_without_newline('path.open("w", encoding="utf-8")')
    assert _text_writes_without_newline('p.write_text("x", encoding="utf-8")')
    assert not _text_writes_without_newline(
        'path.open("w", encoding="utf-8", newline="\\n")'
    )
    assert not _text_writes_without_newline('path.open("rb")')


def test_no_tracked_evidence_artifact_contains_crlf():
    """The property itself, checked against the committed bytes rather than
    against the code that produced them."""

    listed = subprocess.run(
        ["git", "ls-files", "-z", "docs/evidence"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    names = [n for n in listed.stdout.decode("utf-8").split("\0") if n]
    assert names

    offenders = [n for n in names if b"\r\n" in (ROOT / n).read_bytes()]
    assert not offenders, f"CRLF in retained evidence: {offenders}"
