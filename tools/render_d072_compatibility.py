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
    outside = sum(
        1 for row in rows if row["v2_confidence"] not in ALLOWED_CONFIDENCES
    )
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


def _replace(text: str, name: str, body: str) -> str:
    pattern = re.compile(
        rf"(?<=<!-- generated:{re.escape(name)} -->\n)"
        rf".*?"
        rf"(?=\n<!-- /generated:{re.escape(name)} -->)",
        re.DOTALL,
    )
    replaced, count = pattern.subn(lambda _: body, text, count=1)
    if count != 1:
        raise SystemExit(f"missing generated region {name!r} in {DOCUMENT_PATH}")
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
    args = parser.parse_args(argv)

    document = load_corpus()
    current = DOCUMENT_PATH.read_text(encoding="utf-8")
    rendered = render_document(current, document)

    if args.check:
        if rendered != current:
            print(
                f"{DOCUMENT_PATH} is out of date with {CORPUS_PATH};"
                " run tools/render_d072_compatibility.py",
                file=sys.stderr,
            )
            return 1
        return 0

    if rendered != current:
        DOCUMENT_PATH.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"rewrote {DOCUMENT_PATH}")
    else:
        print(f"{DOCUMENT_PATH} already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
