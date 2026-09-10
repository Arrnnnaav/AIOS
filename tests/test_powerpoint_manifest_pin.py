"""The documented PowerPoint manifest is recomputed, not trusted.

`28dbaf2d` is cited in CLAUDE.md, DECISIONS.md, ROADMAP.md and the evidence
documents as the bundle production runs. Until now it appeared in no test: the
figure could drift from the sources and nothing would fail, which is the same
shape as a measured number that names no record (D034).

A fifth independent review pointed out that `plugins/bundled/` holds excel,
synthetic and vscode but no PowerPoint bundle, so the hermetic lane never
touched the one plugin production actually runs.

This recomputes the manifest from tracked sources and compares it to the
documented digest. It needs no private key: the manifest digest is taken over
the canonical manifest bytes *before* signing, so a reviewer with a clean
checkout can reproduce it -- which is exactly how the last two reviews verified
it themselves.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ghostplugin  # noqa: E402

SPEC = ROOT / "plugins" / "sources" / "powerpoint" / "plugin-source.json"

#: The digest every tracking document names as the current PowerPoint bundle.
DOCUMENTED = "28dbaf2d372c55144e289316a1b92dd25185281351cd685a8e735ee9d759a836"


def _manifest_digest() -> tuple[str, int]:
    """Rebuild the manifest from tracked sources; return its digest and size."""

    specification = json.loads(SPEC.read_text(encoding="utf-8"))
    files = build_ghostplugin._collect(ROOT, specification)
    manifest = {
        "schema_version": 1,
        "plugin_id": specification["plugin_id"],
        "version": specification["version"],
        "plugin_api_version": 2 if specification.get("adapter_api") else 1,
        "core_compatibility": specification["core_compatibility"],
        "applications": specification["applications"],
        "signing_key_id": specification["signing_key_id"],
        "adapter_api": specification.get("adapter_api"),
        "files": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())
        },
    }
    raw = build_ghostplugin._canonical(manifest)
    return hashlib.sha256(raw).hexdigest(), len(files)


def test_the_powerpoint_manifest_still_reproduces_from_tracked_sources():
    """The property: a clean checkout builds the bundle production runs."""

    digest, count = _manifest_digest()

    assert count == 24, count
    assert digest == DOCUMENTED, (
        f"PowerPoint manifest drifted: rebuilt {digest}, documented {DOCUMENTED}. "
        "Either the payload changed and every document naming the old digest is "
        "now stale, or the pin is wrong."
    )


def test_every_document_naming_a_powerpoint_manifest_names_this_one():
    """A digest quoted in prose is a claim, and this is what checks it.

    Superseded digests are allowed to appear -- the decision history has to be
    able to say what was replaced -- but only where the surrounding text marks
    them as superseded, which is asserted by requiring the current one to be
    present in any file that mentions the plugin's manifest at all.
    """

    superseded = {
        "c048e47b2ec066ae23aa62d1aa18471a1f0118c47a1320a086859731cd63925e",
        "48e6e4f4d67dade069d8bcac5ce621b5eb1dc330c66e2550ed0e323cb177baea",
        "61b39b653eba7991c563e9dbcd2564cdd3cdc93bffc0263e1549e9eec46ab424",
    }
    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.md"], cwd=ROOT, capture_output=True, check=False
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")

    offenders = []
    for name in [n for n in listed.stdout.decode("utf-8").split("\0") if n]:
        text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
        mentioned = {value for value in superseded if value[:8] in text}
        if not mentioned:
            continue
        # A document may cite a superseded digest only while also naming the
        # current one, so a reader is never left with the old value alone.
        if DOCUMENTED[:8] not in text:
            offenders.append(f"{name}: cites {sorted(v[:8] for v in mentioned)} only")
    assert not offenders, "superseded manifests cited without the current one:\n" + (
        "\n".join(offenders)
    )


def test_the_pin_is_not_vacuous():
    """A digest constant that matched nothing would pass silently."""

    assert re.fullmatch(r"[0-9a-f]{64}", DOCUMENTED)
    assert SPEC.is_file()
