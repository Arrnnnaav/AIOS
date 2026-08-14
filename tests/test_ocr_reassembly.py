"""Wrapped labels, and the merge that fixes them without inventing new ones.

Fixtures are the spike's REAL reads, not invented strings.
"""

from ghostcursor.perception.ocr import OcrRead, reassemble
from rapidfuzz import fuzz


def _texts(reads):
    return [r.text for r in reads]


def _best(reads, target):
    return max((fuzz.ratio(r.text.lower(), target.lower()) for r in reads), default=0)


# Real Canva editor geometry: a two-line tool label, ~60px wide, 16px lines.
MAGIC = [
    OcrRead(text="Magic", bbox=(100, 200, 160, 216)),
    OcrRead(text="Expand", bbox=(98, 218, 168, 234)),
]
# A different real tool, one grid cell to the left.
MAGIC_EDIT = [OcrRead(text="Magic Edit", bbox=(10, 200, 90, 216))]


def test_recall_a_wrapped_label_is_reassembled():
    """The false-NEGATIVE direction: the feature's whole purpose."""
    merged = reassemble(MAGIC)
    assert _best(merged, "Magic Expand") >= 95, (
        f"'Magic Expand' was not recovered from its parts: {_texts(merged)}"
    )


def test_the_original_parts_are_still_offered():
    """A merge that guesses wrong must not LOSE a match the parts would make."""
    merged = reassemble(MAGIC)
    assert "Magic" in _texts(merged) and "Expand" in _texts(merged)


def test_reassembly_does_not_manufacture_a_match_across_unrelated_labels():
    """The false-POSITIVE direction — as load-bearing as recall.

    Acrobat's tool list stacks unrelated operations vertically at exactly the
    spacing a wrapped label uses. Merging them must not invent a target.
    """
    acrobat = [
        OcrRead(text="Redact a PDF", bbox=(40, 700, 180, 718)),
        OcrRead(text="Compress a PDF", bbox=(40, 750, 200, 768)),
    ]
    merged = reassemble(acrobat)
    for invented in ("Redact a PDF Compress", "Compress a PDF Redact"):
        assert _best(merged, invented) < 95, (
            f"reassembly manufactured {invented!r}: {_texts(merged)}"
        )


def test_reassembly_does_not_merge_across_a_panel_boundary():
    """Canva editor: 'Crop' and 'Pixel Eraser' are adjacent rows, unrelated."""
    canva = [
        OcrRead(text="Crop", bbox=(160, 460, 210, 484)),
        OcrRead(text="Pixel Eraser", bbox=(160, 540, 275, 564)),
    ]
    merged = reassemble(canva)
    assert _best(merged, "Crop Pixel Eraser") < 95, (
        f"unrelated rows were merged: {_texts(merged)}"
    )


def test_a_wrapped_label_does_not_match_its_neighbour():
    """The exact dangerous case from the spike, end to end."""
    merged = reassemble(MAGIC + MAGIC_EDIT)
    expand = [r for r in merged if fuzz.ratio(r.text.lower(), "magic expand") >= 95]
    assert expand, "Magic Expand still unrecoverable"
    for read in expand:
        assert fuzz.ratio(read.text.lower(), "magic edit") < 95


def test_at_most_three_reads_merge_into_one_candidate():
    stack = [
        OcrRead(text=f"w{i}", bbox=(100, 200 + i * 18, 140, 214 + i * 18))
        for i in range(6)
    ]
    for read in reassemble(stack):
        assert len(read.text.split()) <= 3
