"""Thin command-line manager over the single ``PluginStore`` authority."""

from __future__ import annotations

import argparse
from pathlib import Path

from ghostcursor.plugins.platform import developer_store, production_store
from ghostcursor.plugins.store import PluginStoreError


def _store(developer: bool):
    return developer_store() if developer else production_store()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostcursor plugins")
    parser.add_argument(
        "--developer",
        action="store_true",
        help="use the physically separate unsigned-development store",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install")
    install.add_argument("bundle", type=Path)
    enable = commands.add_parser("enable")
    enable.add_argument("plugin_id")
    enable.add_argument("version")
    disable = commands.add_parser("disable")
    disable.add_argument("plugin_id")
    uninstall = commands.add_parser("uninstall")
    uninstall.add_argument("plugin_id")
    uninstall.add_argument("version")
    commands.add_parser("list")
    args = parser.parse_args(argv)

    store = _store(args.developer)
    try:
        if args.command == "install":
            item = store.install(args.bundle)
            print(f"installed {item.plugin_id} {item.version} ({item.state.value})")
        elif args.command == "enable":
            item = store.enable(args.plugin_id, args.version)
            print(f"enabled {item.plugin_id} {item.version}")
        elif args.command == "disable":
            store.disable(args.plugin_id)
            print(f"disabled {args.plugin_id}")
        elif args.command == "uninstall":
            store.uninstall(args.plugin_id, args.version)
            print(f"uninstalled {args.plugin_id} {args.version}")
        else:
            marker = " [DEVELOPER STORE: unsigned plugins allowed]" if args.developer else ""
            print(f"GhostCursor plugins{marker}")
            for item in store.list_installed():
                signature = "signed" if item.signed else "UNSIGNED-DEVELOPER"
                print(
                    f"{item.plugin_id} {item.version} {item.state.value} "
                    f"{signature} — {item.compatibility.reason}"
                )
    except (PluginStoreError, OSError, ValueError) as exc:
        print(f"plugin operation refused: {exc}")
        return 2
    return 0
