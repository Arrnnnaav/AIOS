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

The first version read ONE citation shape -- a two-column table row
`| `name.json` | `<digest>` |` -- which covered eight triples and, by
construction, not the counted acceptance campaign's own report, because that
document writes the name and the digest in the SAME cell. The activation review
demonstrated it: a staged rewrite of `"nodes": 255` to `111` in
`act-acceptance-campaign-2026-09-11.json` passed the full 2587-test lane while
the document went on publishing a digest describing no file.

So the rule no longer depends on the author's choice of table layout. It pairs a
cited filename with a digest on the SAME LINE, whatever punctuation separates
them -- the same move the evidence-hygiene scan made when it stopped enumerating
separators -- and a coverage test names the artifacts that must be cited, so a
citation cannot simply be deleted to make this pass (D137).
"""

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"

#: A retained artifact's filename, and a full SHA-256. Matched SEPARATELY,
#: because the documents pair them in at least three layouts: a two-column
#: table row, one cell holding `name`, `digest`, and a prose sentence. The
#: layout is the author's free choice, so a rule keyed to one layout is a rule
#: the next document walks past.
_ARTIFACT = re.compile(r"`([\w.\-]+\.(?:jsonl|json))`")
_DIGEST = re.compile(r"\b([0-9a-f]{64})\b")

#: Artifacts whose citation must exist. Without this, deleting a citation makes
#: the check below pass -- "the guard is itself unguarded" (D133) -- and the
#: campaign report is precisely the artifact whose absence was the defect.
_MUST_BE_CITED = (
    "act-acceptance-campaign-2026-09-11.json",
    "act-live-manager-d131-r1.jsonl",
)


def _cited_digests():
    """Every (document, artifact, digest) triple stated on one line."""

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
        for line in text.splitlines():
            artifacts = _ARTIFACT.findall(line)
            digests = _DIGEST.findall(line)
            # One of each on a line is an unambiguous pairing. Several of
            # either is a layout nothing here uses, and pairing them
            # positionally would invent a claim the document never made.
            if len(artifacts) == 1 and len(digests) == 1:
                triples.append((name, artifacts[0], digests[0]))
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


def test_the_load_bearing_artifacts_are_actually_cited():
    """Coverage, by name. The counted acceptance campaign's machine-readable
    record was protected by nothing until an activation review staged an edit
    to it and watched the full 2587-test lane pass."""

    cited = {artifact for _, artifact, _ in _cited_digests()}

    missing = [name for name in _MUST_BE_CITED if name not in cited]
    assert not missing, (
        f"no evidence document publishes a digest for {missing}. A retained "
        "artifact nobody cites is an artifact nobody can check."
    )


def test_the_pairing_reads_the_shapes_the_documents_actually_use():
    """Each of these is a real layout under `docs/evidence/` at this commit.
    The table-row-only rule read the first and missed the second -- and the
    second is the one the acceptance campaign uses."""

    digest = "a" * 64

    def paired(line):
        return len(_ARTIFACT.findall(line)) == 1 and len(_DIGEST.findall(line)) == 1

    assert paired("| `run.jsonl` | `" + digest + "` |")
    assert paired("| Report | `run.json`, `" + digest + "` |")
    assert paired("The retained transcript `run.jsonl` hashes `" + digest + "`.")
    # A digest with no artifact named on the line states no claim about a file.
    assert not paired("| Manifest | `" + digest + "` |")
