import json
from pathlib import Path

import pytest

from ghostcursor.packs.registry import PackRegistry


def test_builtin_packs_load_and_validate_recipes():
    registry = PackRegistry()
    packs = registry.installed_packs()

    assert {pack.pack_id for pack in packs} == {"synthetic", "notepad", "vscode"}
    assert {intent for pack in packs for intent in pack.intent_ids} >= {
        "EXPORT_DATA", "OPEN_FOLDER", "OPEN_TERMINAL"
    }


def test_match_values_requires_both_executable_and_title_when_both_are_declared():
    registry = PackRegistry()

    assert registry.match_values("python.exe", "Synthetic Export").pack_id == "synthetic"
    assert registry.match_values("python.exe", "Another Python Window") is None
    assert registry.match_values("Code.exe", "project - Visual Studio Code").pack_id == "vscode"
    assert registry.match_values("notepad.exe", "Untitled - Notepad").pack_id == "notepad"


def test_legacy_manifest_fixtures_are_not_part_of_the_v2_registry():
    assert not hasattr(PackRegistry().installed_packs()[0], "recipe_directory")

def test_v2_registry_exposes_only_verified_identity_fields():
    for pack in PackRegistry().installed_packs():
        assert set(pack.__dataclass_fields__) == {
            "pack_id", "display_name", "executable_names", "title_patterns", "intent_ids"
        }


def test_v2_registry_has_no_recipe_lookup_authority():
    assert not hasattr(PackRegistry(), "recipe_for")
