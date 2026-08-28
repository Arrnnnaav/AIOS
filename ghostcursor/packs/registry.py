"""Projection of verified application identities for window matching.

The v2 activation loader is the sole artifact authority. This module does not
scan, load, or resolve recipes.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import win32gui
import win32process

from ghostcursor.perception.appinfo import _exe_path_for_pid
_NON_EMPTY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class AppPack:
    pack_id: str
    display_name: str
    executable_names: tuple[str, ...]
    title_patterns: tuple[str, ...]
    intent_ids: tuple[str, ...]


class PackRegistry:
    """Project verified application identities without loading recipes."""

    def __init__(self, packs: tuple[AppPack, ...] | None = None) -> None:
        if packs is None:
            from ghostcursor.packs.activation import load_catalog

            project_root = Path(__file__).resolve().parent.parent.parent
            self._packs = tuple(
                AppPack(
                    pack_id=pack.pack_id,
                    display_name=pack.pack_value["display_name"],
                    executable_names=tuple(pack.pack_value["executable_names"]),
                    title_patterns=tuple(pack.pack_value["title_patterns"]),
                    intent_ids=tuple(pack.intents),
                )
                for pack in load_catalog(project_root).packs.values()
                if pack.pack_value.get("pack_kind") == "application"
            )
        else:
            self._packs = tuple(packs)

    @classmethod
    def from_verified(cls, packs) -> "PackRegistry":
        """Build a registry from already-verified pack identities.

        The v2 constructor. `PackRegistry` performs no scanning and no loading
        of its own here: it receives identities that `activation.py` already
        verified against exact digests and strict schemas, and does nothing but
        match windows for `daemon.py`.

        The registry receives only identities from the verified catalog. It
        performs no filesystem discovery and has no recipe authority.
        """
        registry = cls.__new__(cls)
        registry.root = Path(__file__).resolve().parent
        registry._packs = tuple(
            AppPack(
                pack_id=pack.pack_id,
                display_name=pack.pack_value["display_name"],
                executable_names=tuple(pack.pack_value["executable_names"]),
                title_patterns=tuple(pack.pack_value["title_patterns"]),
                intent_ids=tuple(pack.intents),
            )
            for pack in packs
            if pack.pack_value.get("pack_kind") == "application"
        )
        return registry

    def installed_packs(self) -> tuple[AppPack, ...]:
        return self._packs

    def reload(self) -> None:
        """Compatibility no-op; catalog reloads create a new registry."""
        return None

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
