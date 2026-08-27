"""Strict, local application-pack registry.

Pack manifests are metadata, not executable authority. Every recipe path is
resolved beneath the pack's own trusted directory, symlinks are rejected, and
the existing recipe schema remains the final validator.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import win32gui
import win32process

from ghostcursor.perception.appinfo import _exe_path_for_pid
from ghostcursor.reasoning.schema import Recipe


_MANIFEST_FIELDS = {
    "pack_id",
    "display_name",
    "executable_names",
    "title_patterns",
    "version_constraints",
    "recipe_directory",
    "intent_ids",
}
_NON_EMPTY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class AppPack:
    pack_id: str
    display_name: str
    executable_names: tuple[str, ...]
    title_patterns: tuple[str, ...]
    version_constraints: tuple[str, ...]
    recipe_directory: Path
    intent_ids: tuple[str, ...]

    def recipe_paths(self) -> tuple[Path, ...]:
        """Return only schema-valid recipe files under this pack directory."""
        trusted = self.recipe_directory.resolve(strict=True)
        if self.recipe_directory.is_symlink():
            raise ValueError(f"recipe directory is a symlink: {self.pack_id}")
        paths: list[Path] = []
        for path in sorted(trusted.glob("*.json")):
            if path.is_symlink() or path.resolve().parent != trusted:
                raise ValueError(f"recipe path is outside trusted directory: {path}")
            Recipe.load(path)
            paths.append(path)
        return tuple(paths)

    def recipe_for_intent(self, intent_id: str) -> Path | None:
        if intent_id not in self.intent_ids:
            return None
        paths = self.recipe_paths()
        for path in paths:
            recipe = Recipe.load(path)
            if recipe.intent.casefold() == intent_id.casefold() or path.stem.casefold() == intent_id.casefold():
                return path
        # A one-intent pack may use a human-readable recipe filename. The
        # manifest remains the authority for the intent-to-recipe relation;
        # this fallback is intentionally unavailable when a pack grows more
        # than one recipe and therefore becomes ambiguous.
        if len(self.intent_ids) == 1 and len(paths) == 1:
            return paths[0]
        return None


class PackRegistry:
    """Load strict manifests and match visible windows without model input."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = (Path(root) if root is not None else Path(__file__).resolve().parent).resolve()
        self._packs: tuple[AppPack, ...] | None = None

    @classmethod
    def from_verified(cls, packs) -> "PackRegistry":
        """Build a registry from already-verified pack identities.

        The v2 constructor. `PackRegistry` performs no scanning and no loading
        of its own here: it receives identities that `activation.py` already
        verified against exact digests and strict schemas, and does nothing but
        match windows for `daemon.py`.

        The legacy `__init__` still globs `manifests/*.json` and is still what
        production uses; the atomic cutover removes it along with the manifest
        directory. Both exist only during the migration, and only this one
        derives identity from a verified graph.
        """
        registry = cls.__new__(cls)
        registry.root = Path(__file__).resolve().parent
        registry._packs = tuple(
            AppPack(
                pack_id=pack.pack_id,
                display_name=pack.pack_value["display_name"],
                executable_names=tuple(pack.pack_value["executable_names"]),
                title_patterns=tuple(pack.pack_value["title_patterns"]),
                version_constraints=(),
                recipe_directory=pack.directory,
                intent_ids=tuple(pack.intents),
            )
            for pack in packs
            if pack.pack_value.get("pack_kind") == "application"
        )
        return registry

    def installed_packs(self) -> tuple[AppPack, ...]:
        if self._packs is None:
            manifests = sorted(self.root.glob("manifests/*.json"))
            self._packs = tuple(self._load_manifest(path) for path in manifests)
        return self._packs

    def reload(self) -> None:
        self._packs = None

    def _load_manifest(self, path: Path) -> AppPack:
        if path.is_symlink():
            raise ValueError(f"manifest is a symlink: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"manifest must be an object: {path}")
        unknown = set(data) - _MANIFEST_FIELDS
        missing = _MANIFEST_FIELDS - set(data)
        if unknown:
            raise ValueError(f"unknown manifest fields: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing manifest fields: {sorted(missing)}")

        pack_id = data["pack_id"]
        display_name = data["display_name"]
        if not isinstance(pack_id, str) or not _NON_EMPTY_ID.fullmatch(pack_id):
            raise ValueError("pack_id must be a simple non-empty identifier")
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("display_name must be a non-empty string")

        def strings(name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
            value = data[name]
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{name} must be a list of strings")
            if not allow_empty and not value:
                raise ValueError(f"{name} must not be empty")
            if any(not item.strip() for item in value):
                raise ValueError(f"{name} contains an empty string")
            return tuple(value)

        executable_names = strings("executable_names", allow_empty=False)
        title_patterns = strings("title_patterns", allow_empty=False)
        version_constraints = strings("version_constraints")
        intent_ids = strings("intent_ids")
        for pattern in title_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid title pattern {pattern!r}: {exc}") from exc

        if not isinstance(data["recipe_directory"], str) or not data["recipe_directory"].strip():
            raise ValueError("recipe_directory must be a non-empty string")
        pack_root = path.parent.parent.resolve()
        recipe_directory = (pack_root / "recipes" / data["recipe_directory"]).resolve()
        trusted_recipes = (pack_root / "recipes").resolve()
        if recipe_directory != trusted_recipes and not str(recipe_directory).startswith(str(trusted_recipes) + os.sep):
            raise ValueError("recipe directory is outside the trusted recipes root")
        if not recipe_directory.exists() or not recipe_directory.is_dir() or recipe_directory.is_symlink():
            raise ValueError(f"recipe directory is missing or unsafe: {recipe_directory}")

        pack = AppPack(
            pack_id=pack_id,
            display_name=display_name,
            executable_names=tuple(item.casefold() for item in executable_names),
            title_patterns=title_patterns,
            version_constraints=version_constraints,
            recipe_directory=recipe_directory,
            intent_ids=intent_ids,
        )
        pack.recipe_paths()
        return pack

    def match_values(self, executable_name: str, window_title: str) -> AppPack | None:
        """Match testable foreground identity primitives to an installed pack."""
        return self.match_values_with_reason(executable_name, window_title)[0]

    def match_values_with_reason(
        self, executable_name: str, window_title: str
    ) -> tuple[AppPack | None, str]:
        """Return a match and the identity surfaces that did or did not match."""
        exe = Path(executable_name).name.casefold()
        saw_exe = False
        saw_title = False
        for pack in self.installed_packs():
            exe_match = exe in pack.executable_names
            title_match = any(re.search(pattern, window_title) for pattern in pack.title_patterns)
            saw_exe = saw_exe or exe_match
            saw_title = saw_title or title_match
            if exe_match and title_match:
                return pack, "executable+title matched"
            # Packs may use either identity surface, but an explicit title
            # pattern is required to avoid matching every window owned by a
            # shared host such as python.exe.
            if exe_match and not pack.title_patterns:
                return pack, "executable matched"
            if title_match and not pack.executable_names:
                return pack, "title matched"
        if saw_exe and saw_title:
            return None, "executable matched; title did not match the same pack"
        if saw_exe:
            return None, "executable matched; title pattern failed"
        if saw_title:
            return None, "title matched; executable failed"
        return None, "executable and title failed"

    def match_window(self, hwnd: int) -> AppPack | None:
        if not hwnd or not win32gui.IsWindow(hwnd):
            return None
        title = win32gui.GetWindowText(hwnd)
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            exe_path = _exe_path_for_pid(pid)
        except Exception:
            return None
        return self.match_values(os.path.basename(exe_path or ""), title)

    def recipe_for(self, pack_id: str, intent_id: str) -> Path | None:
        for pack in self.installed_packs():
            if pack.pack_id == pack_id:
                return pack.recipe_for_intent(intent_id)
        return None
