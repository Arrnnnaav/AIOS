"""Render the D072 compatibility evidence tables from the canonical corpus.

`tests/data/d072_compatibility_v1.json` is the one reviewed source of corpus
rows.  This tool projects it into the generated regions of
`docs/evidence/d072-compatibility-corpus.md` so the document can never drift
from the fixture the differential test runs against.

It contains no matcher.  It never computes what v1 or v2 return; it only
formats what the reviewed corpus already records.  A number that appears in the
document but not in the corpus is a number this tool cannot produce.

    py -3.12 tools/render_d072_compatibility.py            # rewrite the document
    py -3.12 tools/render_d072_compatibility.py --check    # verify, never write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "tests" / "data" / "d072_compatibility_v1.json"
DOCUMENT_PATH = REPO_ROOT / "docs" / "evidence" / "d072-compatibility-corpus.md"

DASH = "—"
ALLOWED_CONFIDENCES = (0.0, 0.85, 0.95)


def load_corpus(path: Path = CORPUS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _outcome(intent: str | None, confidence: float) -> str:
    """The `INTENT (0.95)` form shared by every table, or an em dash."""
    if intent is None:
        return DASH
    return f"{intent} ({confidence:g})"


def render_result(rows: list[dict]) -> str:
    agree = sum(
        1
        for row in rows
        if (row["expected_v1"], row["v1_confidence"])
        == (row["expected_v2"], row["v2_confidence"])
    )
    diverge = sum(1 for row in rows if row["diverges"])
    unclassified = sum(
        1 for row in rows if row["diverges"] and row["divergence_class"] is None
    )
    kinds = Counter(row["v2_kind"] for row in rows)
    outside = sum(1 for row in rows if row["v2_confidence"] not in ALLOWED_CONFIDENCES)
    return "\n".join(
        [
            "| | |",
            "|---|---:|",
            f"| Rows | **{len(rows)}** |",
            f"| Agree on intent *and* confidence | {agree} |",
            f"| Diverge | **{diverge}** |",
            "| Divergences matching no class definition (**UNCLASSIFIED**) |"
            f" **{unclassified}** |",
            "| v2 `matched` / `no_match` / `ambiguous` |"
            f" {kinds['matched']} / {kinds['no_match']} / {kinds['ambiguous']} |",
            f"| v2 confidence values outside {{0.0, 0.85, 0.95}} | **{outside}** |",
        ]
    )


def render_classes(document: dict) -> str:
    rows = document["rows"]
    blocks = []
    for name, definition in document["divergence_classes"].items():
        members = [row for row in rows if row["divergence_class"] == name]
        lines = [
            f"**Class {DASH} {name}** ({len(members)} representatives)."
            f" {definition['representatives_summary']}",
            "",
            "| Goal | v1 | v2 |",
            "|---|---|---|",
        ]
        for row in members:
            # A class table names the v2 *kind* where nothing matched, because
            # `ambiguous` and `no_match` are different outcomes and an em dash
            # would collapse them into one.
            v2 = (
                _outcome(row["expected_v2"], row["v2_confidence"])
                if row["v2_kind"] == "matched"
                else row["v2_kind"]
            )
            v1 = _outcome(row["expected_v1"], row["v1_confidence"])
            lines.append(f"| `{row['goal']}` | {v1} | {v2} |")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_corpus(rows: list[dict]) -> str:
    lines = [
        "| Goal | v1 | v1 kind | v2 | v2 kind | class | Origin |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        v1 = _outcome(row["expected_v1"], row["v1_confidence"])
        v2 = _outcome(row["expected_v2"], row["v2_confidence"])
        if row["diverges"]:
            v2 = f"{v2} **DIVERGES**"
        klass = row["divergence_class"] or DASH
        lines.append(
            f"| `{row['goal']}` | {v1} | {row['v1_kind']} |"
            f" {v2} | {row['v2_kind']} | {klass} | {row['origin']} |"
        )
    return "\n".join(lines)


BOM = "﻿"


def canonical_text(raw: bytes) -> str:
    """Decode `raw` into the one text form the document is allowed to have.

    A BOM is removed and every line terminator becomes a bare LF, so the
    rendered bytes are canonical no matter what the file on disk contained.
    Comparing those bytes against the original is then what enforces the
    encoding trusted artifacts require -- UTF-8, LF, no BOM.  Normalising
    without comparing would silently accept the variants; comparing without
    normalising would accept whichever variant the input already had.
    """
    text = raw.decode("utf-8")
    if text.startswith(BOM):
        text = text[len(BOM) :]
    # CRLF first, then any remaining lone CR: an old-Mac terminator and a
    # stray CR inside a line are both line terminators here, and both survive
    # a CRLF-only replacement.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _replace(text: str, name: str, body: str) -> str:
    pattern = re.compile(
        rf"(?<=<!-- generated:{re.escape(name)} -->\n)"
        rf".*?"
        rf"(?=\n<!-- /generated:{re.escape(name)} -->)",
        re.DOTALL,
    )
    replaced, count = pattern.subn(lambda _: body, text, count=1)
    if count != 1:
        raise SystemExit(f"missing generated region {name!r}")
    return replaced


def render_document(text: str, document: dict) -> str:
    rows = document["rows"]
    text = _replace(text, "result", render_result(rows))
    text = _replace(text, "classes", render_classes(document))
    text = _replace(text, "corpus", render_corpus(rows))
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the document already matches the corpus; never write",
    )
    parser.add_argument(
        "--document",
        type=Path,
        default=DOCUMENT_PATH,
        help=(
            "the document to render or check (default: the committed evidence"
            " document). Tests point this at a copy so a regression check never"
            " writes to a tracked file."
        ),
    )
    args = parser.parse_args(argv)

    document = load_corpus()
    document_path: Path = args.document

    # Bytes, never `read_text()`.  Text mode on Windows folds CRLF to LF on the
    # way in, so a CRLF copy of this document would read back identical to the
    # LF bytes the renderer emits and `--check` would pass over a file whose
    # bytes differ.
    current = document_path.read_bytes()
    rendered = render_document(canonical_text(current), document).encode("utf-8")

    if args.check:
        if rendered != current:
            print(
                f"{document_path} is out of date with {CORPUS_PATH};"
                " run tools/render_d072_compatibility.py",
                file=sys.stderr,
            )
            return 1
        return 0

    if rendered != current:
        document_path.write_bytes(rendered)
        print(f"rewrote {document_path}")
    else:
        print(f"{document_path} already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
