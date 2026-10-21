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
    cat = commands.add_parser("catalog")
    cat.add_argument("directory", type=Path)
    cat.add_argument("--search", default="", help="filter by id/app/metadata substring")
    cat.add_argument("--sort", choices=("id", "version", "latest"), default="id")
    cat.add_argument("--only", choices=("signed", "compatible", "latest"))
    cat.add_argument("--app", help="only plugins targeting this application")
    cat.add_argument("--write", type=Path, help="write a read-only index.json here")
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
        elif args.command == "catalog":
            import json

            from ghostcursor.plugins.marketplace import (
                build_index,
                catalog,
                filter_entries,
                search,
                sort_entries,
            )

            entries = catalog(
                args.directory,
                trusted_keys=store.trusted_keys,
                core_version=store.core_version,
            )
            shown = search(entries, args.search) if args.search else entries
            shown = filter_entries(
                shown,
                signed=True if args.only == "signed" else None,
                compatible=True if args.only == "compatible" else None,
                latest=True if args.only == "latest" else None,
                app=args.app,
            )
            shown = sort_entries(shown, by=args.sort)
            print(f"Available plugins in {args.directory}:")
            for entry in shown:
                print(f"  {entry.as_line()}")
            if not shown:
                print("  (no matching .ghostplugin bundles found)")
            if args.write:
                args.write.write_text(
                    json.dumps(build_index(entries), indent=1),
                    encoding="utf-8",
                    newline="\n",
                )
                print(f"wrote catalog index -> {args.write}")
        else:
            marker = (
                " [DEVELOPER STORE: unsigned plugins allowed]" if args.developer else ""
            )
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
