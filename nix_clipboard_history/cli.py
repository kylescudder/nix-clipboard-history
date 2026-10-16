from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict

from . import __version__
from .config import Config
from .store import Store


def capture(config: Config, kind: str) -> int:
    import os

    from .wayland import active_window

    if os.environ.get("CLIPBOARD_STATE", "data") != "data":
        return 0
    with Store(config=config) as store:
        if store.paused:
            return 0
        target = active_window()
        if target.app_class.casefold() in {name.casefold() for name in config.excluded_apps}:
            return 0
        data = sys.stdin.buffer.read(config.max_item_bytes + 1)
        store.add(data, kind, target.app_class)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Searchable text and image clipboard history for Hyprland."
    )
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="command")
    show = commands.add_parser("show", help="Open the clipboard popup (default)")
    show.add_argument("--copy-only", action="store_true", help="Copy without automatically pasting")
    show.add_argument(
        "--windowed", action="store_true", help="Use a normal GTK window for development"
    )
    commands.add_parser("daemon", help="Watch the Wayland clipboard; run once per session")
    ingest = commands.add_parser("capture", help="Read one item from stdin (used by the watcher)")
    ingest.add_argument("--kind", choices=["text", "image"], default="text")
    listing = commands.add_parser("list", help="List history metadata as JSON; content is omitted")
    listing.add_argument("query", nargs="?", default="")
    listing.add_argument("--kind", choices=["all", "text", "image", "pinned"], default="all")
    listing.add_argument("--limit", type=int, default=100)
    for command in ("copy", "pin", "delete"):
        item = commands.add_parser(command, help=f"{command.capitalize()} an item by its ID")
        item.add_argument("id", type=int)
    clear = commands.add_parser(
        "clear", help="Delete unpinned history; leaves the clipboard unchanged"
    )
    clear.add_argument("--all", action="store_true", help="Also delete pinned items")
    clear.add_argument("--yes", action="store_true", help="Confirm deletion")
    commands.add_parser("pause", help="Pause capture")
    commands.add_parser("resume", help="Resume capture")
    commands.add_parser("status", help="Show item count, size, and capture pause state as JSON")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser()
    args = arguments.parse_args(argv)
    command = args.command or "show"
    try:
        config = Config.load()
        if command == "capture":
            return capture(config, args.kind)
        if command == "daemon":
            from .daemon import run

            return run(config)
        if command == "show":
            from .gui import run

            return run(
                config,
                copy_only=getattr(args, "copy_only", False),
                windowed=getattr(args, "windowed", False),
            )
        with Store(config=config) as store:
            store.prune()
            if command == "list":
                if args.limit < 1:
                    arguments.error("--limit must be positive")
                print(
                    json.dumps(
                        [asdict(e) for e in store.list(args.query, args.kind, args.limit)],
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            elif command == "status":
                print(json.dumps({**store.stats(), "daemon_running": store.daemon_running()}))
            elif command in ("pause", "resume"):
                store.set_paused(command == "pause")
                print("Capture paused" if command == "pause" else "Capture resumed")
            elif command == "clear":
                if not args.yes:
                    arguments.error(
                        "Use clear --yes to confirm deletion (add --all to include pins)"
                    )
                store.clear(args.all)
            elif command == "pin":
                store.get(args.id)
                store.pin(args.id)
            elif command == "delete":
                store.get(args.id)
                store.delete(args.id)
            elif command == "copy":
                from .wayland import copy

                copy(*store.get(args.id))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, ImportError) as error:
        print(f"nix-clipboard-history: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
