"""Logging-only foreground application watcher.

This is deliberately not a tray application and does not start tours. It is a
small validation surface for pack matching before startup UX is introduced.
"""
from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from typing import Callable
from pathlib import Path

import win32gui
import win32process

from ghostcursor.packs.registry import AppPack, PackRegistry
from ghostcursor.packs.activation import load_catalog
from ghostcursor.perception.appinfo import _exe_path_for_pid


@dataclass(frozen=True)
class ForegroundIdentity:
    hwnd: int
    executable_name: str
    title: str


def foreground_identity(hwnd: int | None = None) -> ForegroundIdentity | None:
    hwnd = int(hwnd or win32gui.GetForegroundWindow())
    if not hwnd or not win32gui.IsWindow(hwnd):
        return None
    title = win32gui.GetWindowText(hwnd)
    try:
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        exe_path = _exe_path_for_pid(pid)
    except Exception:
        return None
    return ForegroundIdentity(hwnd, os.path.basename(exe_path or ""), title)


class ForegroundWatcher:
    def __init__(
        self,
        registry: PackRegistry | None = None,
        *,
        interval_s: float = 0.5,
        foreground_source: Callable[[], ForegroundIdentity | None] = foreground_identity,
        log: Callable[[str], None] = print,
    ) -> None:
        if registry is not None:
            self.registry = registry
        else:
            project_root = Path(__file__).resolve().parent.parent
            catalog = load_catalog(project_root)
            self.registry = PackRegistry.from_verified(catalog.packs.values())
        self.interval_s = interval_s
        self.foreground_source = foreground_source
        self.log = log
        self._last_identity: tuple[int, str, str] | None = None
        self._last_pack_id: str | None = None

    def poll_once(self) -> AppPack | None:
        identity = self.foreground_source()
        if identity is None:
            return None
        key = (identity.hwnd, identity.executable_name, identity.title)
        if key == self._last_identity:
            return self.registry.match_values(identity.executable_name, identity.title)
        self._last_identity = key
        pack, reason = self.registry.match_values_with_reason(
            identity.executable_name, identity.title
        )
        title_summary = identity.title[:60]
        if pack is None:
            self.log(
                f"Ghost Cursor: pack miss exe={identity.executable_name!r} "
                f"title={title_summary!r} ({reason})"
            )
        elif pack.pack_id != self._last_pack_id:
            self.log(
                f"Ghost Cursor: pack activated {pack.pack_id!r} "
                f"for exe={identity.executable_name!r} title={title_summary!r}"
            )
        self._last_pack_id = pack.pack_id if pack is not None else None
        return pack

    def run(self, *, seconds: float | None = None) -> None:
        started = time.monotonic()
        try:
            while seconds is None or time.monotonic() - started < seconds:
                self.poll_once()
                time.sleep(self.interval_s)
        except KeyboardInterrupt:
            self.log("Ghost Cursor: foreground watcher stopped")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ghost Cursor foreground pack watcher")
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--seconds", type=float, default=None)
    args = parser.parse_args()
    ForegroundWatcher(interval_s=args.interval).run(seconds=args.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
