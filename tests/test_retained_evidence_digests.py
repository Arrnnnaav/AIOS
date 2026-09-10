"""An evidence document's digests must match the artifacts it cites.

`act-live-manager-d131-run.md` publishes a SHA-256 for each retained artifact,
and until now nothing checked them. A review demonstrated the consequence: it
edited one of those artifacts to plant a leak, which changed the file's bytes
and therefore invalidated the digest the document publishes -- and the entire
2504-test lane passed. The document would have gone on asserting a digest that
described no file in the repository.

That is the same class as an unpinned manifest (D130): a number quoted in prose
is a claim, and a claim nothing reads is not evidence (D032, D034).

The digests are parsed out of the documents rather than restated here, so this
test cannot drift from what a reader actually sees.
"""

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"

#: `| `name.jsonl` | `<64 hex>` |` -- the table shape the evidence documents use.
_ROW = re.compile(r"\|\s*`([\w.\-]+\.(?:jsonl|json))`\s*\|\s*`([0-9a-f]{64})`\s*\|")


def _cited_digests():
    """Every (document, artifact, digest) triple stated in a table row."""

    listed = subprocess.run(
        ["git", "ls-files", "-z", "docs/evidence/*.md", "docs/evidence/**/*.md"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    triples = []
    for name in [n for n in listed.stdout.decode("utf-8").split("\0") if n]:
        text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
        for artifact, digest in _ROW.findall(text):
            triples.append((name, artifact, digest))
    return triples


def test_there_are_cited_digests_to_check():
    """Non-vacuity: a regex that matched nothing would make the check below
    pass while verifying no document at all (D018)."""

    triples = _cited_digests()
    assert len(triples) >= 3, triples
    assert any(a.endswith(".jsonl") for _, a, _ in triples)


def test_every_cited_artifact_exists_and_matches_its_published_digest():
    """The property: a reader can recompute what the document claims."""

    problems = []
    for document, artifact, digest in _cited_digests():
        candidates = sorted(EVIDENCE.rglob(artifact))
        if not candidates:
            problems.append(f"{document}: cites {artifact}, which is not retained")
            continue
        for path in candidates:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != digest:
                problems.append(
                    f"{document}: cites {artifact} as {digest[:12]}, "
                    f"but {path.relative_to(ROOT)} hashes {actual[:12]}"
                )
    assert not problems, "evidence digests do not match their artifacts:\n" + "\n".join(
        problems
    )
