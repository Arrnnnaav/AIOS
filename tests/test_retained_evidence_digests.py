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
#: The BASENAME, with any directory prefix consumed: documents cite both
#: `run-1.json` and `docs/evidence/act-live-manager-d123-r5.jsonl`, and the
#: first version matched only the bare form -- so the one artifact whose
#: citation both spans two lines AND carries a path was missed twice over.
_ARTIFACT = re.compile(r"`(?:[\w.\-]+/)*([\w.\-]+\.(?:jsonl|json))`")
_DIGEST = re.compile(r"\b([0-9a-f]{64})\b")

#: Artifacts whose citation must exist. Without this, deleting a citation makes
#: the check below pass -- "the guard is itself unguarded" (D133) -- and the
#: campaign report is precisely the artifact whose absence was the defect.
#: DERIVED, not listed: every tracked `.json`/`.jsonl` under `docs/evidence/`
#: must be cited by some document. A hand-kept tuple protected two artifacts
#: and left seven unprotected, and for those seven an ambiguous citation line
#: (two digests, say) silently dropped the artifact from the check even as its
#: bytes changed -- pass by omission, which is the shape this test exists to
#: refuse (D138).
_EXPECTED_UNCITED = frozenset()


def _tracked_paths():
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    return [n for n in listed.stdout.decode("utf-8").split(chr(0)) if n]


def _retained_artifacts():
    listed = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "docs/evidence/*.json",
            "docs/evidence/**/*.json",
            "docs/evidence/*.jsonl",
            "docs/evidence/**/*.jsonl",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    return sorted(
        {Path(n).name for n in listed.stdout.decode("utf-8").split(chr(0)) if n}
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
        # Lines first -- table rows and single-cell citations -- then
        # paragraphs, because prose wraps: `act-live-manager-pointer.md` puts
        # the filename on one line and its SHA-256 two lines later, and a
        # line-only rule silently dropped it. A paragraph with exactly one of
        # each is still an unambiguous pairing; a table (many of both in one
        # block) is already covered line by line.
        paragraphs = re.split(chr(10) + r"[ " + chr(92) + r"t]*" + chr(10), text)
        blocks = [(line, False) for line in text.splitlines()]
        blocks += [(para, True) for para in paragraphs]
        for block, paragraph in blocks:
            artifacts = _ARTIFACT.findall(block)
            digests = _DIGEST.findall(block)
            # Several of either states no single claim, and pairing them
            # positionally would invent one the document never made.
            if len(artifacts) != 1 or len(digests) != 1:
                continue
            # A paragraph is a looser container than a line, so it pairs only
            # names that are actually retained artifacts. Without that, a
            # paragraph naming the frozen dataset `model_durability_v1.json`
            # near an unrelated digest manufactured a citation nobody wrote --
            # found by this test failing on its own first draft.
            if paragraph and artifacts[0] not in _retained_artifacts():
                continue
            triples.append((name, artifacts[0], digests[0]))
    return sorted(set(triples))


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
        # Under `docs/evidence/` first, then anywhere tracked: the candidate
        # acceptance documents legitimately cite signed payload members such as
        # `add_slide.json`, which live under `plugins/`. Restricting the search
        # to the evidence tree reported those as "not retained" -- a false
        # accusation, found by this test failing on real citations.
        candidates = sorted(EVIDENCE.rglob(artifact)) or [
            ROOT / n for n in _tracked_paths() if Path(n).name == artifact
        ]
        if not candidates:
            problems.append(f"{document}: cites {artifact}, which is not retained")
            continue
        # A document names ONE file. Several tracked files may share a
        # basename, so the claim holds if any of them has those bytes.
        digests = {hashlib.sha256(path.read_bytes()).hexdigest() for path in candidates}
        if digest not in digests:
            problems.append(
                f"{document}: cites {artifact} as {digest[:12]}, but the "
                f"{len(candidates)} tracked file(s) of that name hash "
                + ", ".join(sorted(d[:12] for d in digests))
            )
    assert not problems, "evidence digests do not match their artifacts:\n" + "\n".join(
        problems
    )


def test_every_retained_artifact_is_cited_by_some_document():
    """Coverage, DERIVED. The counted campaign's machine-readable record was
    protected by nothing until a review staged an edit to it and watched the
    full lane pass; a hand-kept list then protected that one and left the
    receipt-budget records unpinned. A retained artifact nobody cites is an
    artifact nobody can check, and adding one must not be silent (D138)."""

    retained = _retained_artifacts()
    cited = {artifact for _, artifact, _ in _cited_digests()}

    assert len(retained) >= 10, retained
    missing = [n for n in retained if n not in cited and n not in _EXPECTED_UNCITED]
    assert not missing, (
        f"no evidence document publishes a digest for {missing}. Cite each in "
        "the document that relies on it, as `name` and digest on one line."
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
