import json
from pathlib import Path

import pytest

from ghostcursor.packs.registry import PackRegistry


def test_builtin_packs_load_and_validate_recipes():
    registry = PackRegistry()
    packs = registry.installed_packs()

    assert {pack.pack_id for pack in packs} == {"synthetic", "notepad", "vscode"}
    assert registry.recipe_for("synthetic", "EXPORT_DATA") is not None
    assert registry.recipe_for("notepad", "OPEN_NEW_TAB") is not None
    assert registry.recipe_for("vscode", "OPEN_FOLDER") is not None
    assert registry.recipe_for("vscode", "OPEN_TERMINAL") is not None


def test_match_values_requires_both_executable_and_title_when_both_are_declared():
    registry = PackRegistry()

    assert registry.match_values("python.exe", "Synthetic Export").pack_id == "synthetic"
    assert registry.match_values("python.exe", "Another Python Window") is None
    assert registry.match_values("Code.exe", "project - Visual Studio Code").pack_id == "vscode"
    assert registry.match_values("notepad.exe", "Untitled - Notepad").pack_id == "notepad"


def test_unknown_manifest_fields_are_rejected():
    root = Path("tests/fixtures/packs/extra_field")
    with pytest.raises(ValueError, match="unknown manifest fields"):
        PackRegistry(root).installed_packs()

def test_manifest_with_invalid_title_regex_is_rejected():
    root = Path("tests/fixtures/packs/invalid_regex")
    with pytest.raises(ValueError, match="invalid title pattern"):
        PackRegistry(root).installed_packs()


def test_recipe_directory_outside_trusted_root_is_rejected():
    root = Path("tests/fixtures/packs/outside_recipe")
    with pytest.raises(ValueError, match="outside"):
        PackRegistry(root).installed_packs()
