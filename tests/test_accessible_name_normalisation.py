"""Codicon glyphs must not defeat trusted name matching (D069).

VS Code 1.134.0 exposes the Welcome-page action as `' Open Folder...'` --
a private-use Codicon codepoint prefixed to the label -- while the trusted
recipe asks for `'Open Folder...'`. Exact matching therefore misses, which is
why that workflow's tier-1 perception went dark.

The fix is normalisation, deliberately NOT adding the observed glyph to the
recipe: a specific private-use codepoint is version-sensitive and would break
the next time VS Code renumbers its icon font.

Normalisation must stay narrow. It strips *leading* private-use characters and
the whitespace they leave behind, and nothing else -- it is not a fuzzy matcher
and must never lower the grounding floor.
"""

from ghostcursor.perception.uia import (
    matches_trusted_name,
    normalise_accessible_name,
)

# Exactly as observed on VS Code 1.134.0, both spacings.
OBSERVED_SPACED = " Open Folder..."
OBSERVED_TIGHT = "Open Folder..."


def test_strips_a_leading_codicon_and_its_space():
    assert normalise_accessible_name(OBSERVED_SPACED) == "Open Folder..."


def test_strips_a_leading_codicon_with_no_space():
    assert normalise_accessible_name(OBSERVED_TIGHT) == "Open Folder..."


def test_leaves_an_ordinary_name_untouched():
    for name in (
        "Open Folder...",
        "Toggle Panel (Ctrl+J)",
        "Terminal Section",
        "Extensions (Ctrl+Shift+X)",
        "Installed Section",
    ):
        assert normalise_accessible_name(name) == name


def test_does_not_strip_private_use_characters_from_the_middle_or_end():
    """Only a LEADING icon is decoration. Elsewhere it is part of the label."""
    assert normalise_accessible_name("Open  Folder") == "Open  Folder"
    assert normalise_accessible_name("Open Folder ") == "Open Folder "


def test_a_name_that_is_only_a_glyph_normalises_to_empty():
    assert normalise_accessible_name("") == ""
    assert normalise_accessible_name(" ") == ""


def test_handles_empty_and_none():
    assert normalise_accessible_name("") == ""
    assert normalise_accessible_name(None) == ""


# --- trusted matching ------------------------------------------------------

ALLOWED = ("Open Folder...", "Open Folder…", "Open Folder")


def test_a_glyph_prefixed_observation_matches_the_trusted_name():
    assert matches_trusted_name(OBSERVED_SPACED, ALLOWED) is True
    assert matches_trusted_name(OBSERVED_TIGHT, ALLOWED) is True


def test_an_exact_observation_still_matches():
    assert matches_trusted_name("Open Folder...", ALLOWED) is True


def test_an_unrelated_name_does_not_match():
    for name in ("Open File...", "Clone Git Repository...", "New File...", ""):
        assert matches_trusted_name(name, ALLOWED) is False


def test_a_bare_glyph_does_not_match_anything():
    """Normalising to empty must not become a wildcard."""
    assert matches_trusted_name("", ALLOWED) is False


def test_matching_is_not_substring_matching():
    """Normalisation must not smuggle in a looser rung (D030).

    Rung 3 is the substring rung and OCR is barred from it precisely so the
    floor is not decorative. Name normalisation must not reintroduce that
    looseness by the back door.
    """
    assert matches_trusted_name("Do not Open Folder... ever", ALLOWED) is False
