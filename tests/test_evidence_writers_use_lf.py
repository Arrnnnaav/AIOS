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

#: Every tracked module under `tools/` or `ghostcursor/devtools/`, plus the
#: production modules that write a hashed artifact. DERIVED, not listed: a
#: hand-maintained tuple behind a `len >= 10` floor could silently shrink, and
#: removing an entry passed the whole lane (D133). A new writer is covered the
#: moment it is committed, without anyone remembering to add it.
_EXTRA_WRITERS = (
    "ghostcursor/act_staging.py",
    "ghostcursor/brief.py",
    "ghostcursor/reasoning/schema.py",
    "ghostcursor/evaluation/model_gate.py",
)


def _writer_modules():
    listed = subprocess.run(
        ["git", "ls-files", "-z", "tools", "ghostcursor/devtools"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    names = [
        n
        for n in listed.stdout.decode("utf-8").split(chr(0))
        if n.endswith(".py") and not Path(n).name.startswith("__")
    ]
    return sorted(set(names) | set(_EXTRA_WRITERS))


#: Text-writing idioms. The first version knew only `open` and `write_text`, so
#: `NamedTemporaryFile(mode="w")`, `io.open` and a `json.dump` to a text handle
#: all evaded it -- the class enumerated rather than closed, which is the shape
#: this chain keeps reproducing (D133).
_TEXT_OPENERS = {"open", "write_text", "NamedTemporaryFile", "TemporaryFile", "fdopen"}


def _text_writes_without_newline(source: str):
    """Every `open(..., "w")` / `write_text(...)` that does not pin newline."""

    offenders = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in _TEXT_OPENERS:
            continue
        keywords = {kw.arg for kw in node.keywords}
        if "newline" in keywords:
            continue
        if name != "write_text":
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


def test_the_writer_set_is_derived_and_covers_the_known_tools():
    """Non-vacuity, and specifically about derivation: the set comes from git,
    so a new devtool is covered the moment it is committed."""

    modules = _writer_modules()

    missing = [name for name in modules if not (ROOT / name).is_file()]
    assert not missing, missing
    assert len(modules) >= 20, len(modules)
    for required in (
        "ghostcursor/devtools/act_acceptance.py",
        "ghostcursor/devtools/act_campaign.py",
        "ghostcursor/devtools/act_deck_observation.py",
        "tools/render_add_slide_evidence.py",
        "ghostcursor/brief.py",
    ):
        assert required in modules, required


@pytest.mark.parametrize("name", _writer_modules())
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
