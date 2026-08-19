"""Wrapped labels, and the merge that fixes them without inventing new ones.

Fixtures are the spike's REAL reads, not invented strings.
"""

from ghostcursor.perception.ocr import (
    MERGE_CENTRE_TOLERANCE,
    MERGE_VERTICAL_GAP,
    OcrRead,
    reassemble,
)
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

    Acrobat's tool list stacks two unrelated operations vertically, well
    outside the merge geometry (a 32px gap against a ~13.5px threshold at
    these box heights — not "exactly" the wrapped-label spacing, just a
    plausible adjacent pair). Merging them must not invent a target. The
    near-boundary tests below are what actually exercise the threshold.
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


def test_a_non_mergeable_middle_read_breaks_the_chain():
    """Finding 1 (fix round 1): a badge/icon read sitting between two lines of
    a wrapped label must not let the chain jump over it.

    'Magic' and 'Expand' are geometrically close enough that, on their own,
    they would merge (small gap, aligned centres). 'New' sits between them
    vertically but is offset far enough sideways to be unmergeable with
    'Magic'. Before the fix, the loop used `continue` on a failed candidate
    and kept walking, so 'Magic' skipped over 'New' and merged with 'Expand'
    anyway — a bbox spanning a read whose text the merge never named. The
    chain must stop the moment a candidate fails to continue it.
    """
    top = OcrRead(text="Magic", bbox=(100, 200, 160, 216))
    badge = OcrRead(text="New", bbox=(300, 217, 330, 221))
    bottom = OcrRead(text="Expand", bbox=(98, 222, 168, 238))
    merged = reassemble([top, badge, bottom])
    assert "Magic Expand" not in _texts(merged), (
        f"chain jumped over the unmergeable middle read: {_texts(merged)}"
    )


# --- Near-boundary tests (Finding 2, fix round 1) ---------------------------
#
# The tests above prove reassembly doesn't merge OBVIOUSLY unrelated rows.
# They sit comfortably inside the reject region, so a meaningfully looser
# tolerance would still pass them. These derive their gaps from the actual
# constants so a wrong retune of MERGE_VERTICAL_GAP or MERGE_CENTRE_TOLERANCE
# fails one of these directly.

_BOUNDARY_WIDTH = 60
_BOUNDARY_HEIGHT = 20


def _vertical_pair(gap):
    top = OcrRead(
        text="Alpha",
        bbox=(100, 200, 100 + _BOUNDARY_WIDTH, 200 + _BOUNDARY_HEIGHT),
    )
    bottom_top = 200 + _BOUNDARY_HEIGHT + gap
    bottom = OcrRead(
        text="Beta",
        bbox=(
            100,
            bottom_top,
            100 + _BOUNDARY_WIDTH,
            bottom_top + _BOUNDARY_HEIGHT,
        ),
    )
    return [top, bottom]


def _centre_offset_pair(offset):
    top = OcrRead(
        text="Alpha",
        bbox=(100, 200, 100 + _BOUNDARY_WIDTH, 200 + _BOUNDARY_HEIGHT),
    )
    bottom = OcrRead(
        text="Beta",
        bbox=(
            100 + offset,
            200 + _BOUNDARY_HEIGHT,
            100 + offset + _BOUNDARY_WIDTH,
            200 + 2 * _BOUNDARY_HEIGHT,
        ),
    )
    return [top, bottom]


def test_vertical_gap_just_inside_threshold_merges():
    threshold = MERGE_VERTICAL_GAP * _BOUNDARY_HEIGHT
    gap = round(threshold) - 1
    merged = reassemble(_vertical_pair(gap))
    assert "Alpha Beta" in _texts(merged), (
        f"gap {gap} is inside the {threshold} threshold and should merge: "
        f"{_texts(merged)}"
    )


def test_vertical_gap_just_outside_threshold_does_not_merge():
    threshold = MERGE_VERTICAL_GAP * _BOUNDARY_HEIGHT
    gap = round(threshold) + 1
    merged = reassemble(_vertical_pair(gap))
    assert "Alpha Beta" not in _texts(merged), (
        f"gap {gap} is outside the {threshold} threshold and should not "
        f"merge: {_texts(merged)}"
    )


def test_centre_offset_just_inside_threshold_merges():
    threshold = MERGE_CENTRE_TOLERANCE * _BOUNDARY_WIDTH
    offset = round(threshold) - 1
    merged = reassemble(_centre_offset_pair(offset))
    assert "Alpha Beta" in _texts(merged), (
        f"centre offset {offset} is inside the {threshold} threshold and "
        f"should merge: {_texts(merged)}"
    )


def test_centre_offset_just_outside_threshold_does_not_merge():
    threshold = MERGE_CENTRE_TOLERANCE * _BOUNDARY_WIDTH
    offset = round(threshold) + 1
    merged = reassemble(_centre_offset_pair(offset))
    assert "Alpha Beta" not in _texts(merged), (
        f"centre offset {offset} is outside the {threshold} threshold and "
        f"should not merge: {_texts(merged)}"
    )
