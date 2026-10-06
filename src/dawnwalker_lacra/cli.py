"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import ExternalDecoder, PyOozDecoder, Save, SaveError, analyze
from .slots import add, first_free_slot, patch_in_place, recover, scan


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="dawnwalker-lacra")
    sub = result.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="inspect one save without changing it")
    inspect.add_argument("--save", type=Path, required=True)
    inspect.add_argument("--decoder", type=Path)
    scan_cmd = sub.add_parser("scan", help="list manual slots in a directory")
    scan_cmd.add_argument("directory", type=Path)
    repair = sub.add_parser("repair", help="create a repaired copy in a new slot")
    repair.add_argument("--save", type=Path, required=True)
    repair.add_argument("--mode", choices=["add", "patch"], default="add")
    repair.add_argument("--slot", type=int)
    repair.add_argument("--decoder", type=Path)
    repair.add_argument("--dry-run", action="store_true")
    recover_cmd = sub.add_parser("recover", help="restore an in-place PATCH backup")
    recover_cmd.add_argument("backup", type=Path)
    return result


def _decoder(path: Path | None):
    return ExternalDecoder(path) if path else PyOozDecoder()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "scan":
            print(json.dumps({"directory": str(args.directory), "manual_slots": scan(args.directory),
                              "first_free_slot": first_free_slot(args.directory)}, indent=2))
        elif args.command == "inspect":
            save = Save.from_path(args.save, _decoder(args.decoder))
            result = analyze(save)
            print(json.dumps({"sha256": save.sha256, "save_version": save.save_version,
                              "game_version": save.game_version, "status": result.status,
                              "reason": result.reason}, indent=2))
        elif args.command == "recover":
            print(json.dumps(recover(args.backup), indent=2))
        elif args.mode == "patch":
            print(json.dumps(patch_in_place(args.save, _decoder(args.decoder),
                                            dry_run=args.dry_run), indent=2))
        else:
            slot = args.slot if args.slot is not None else first_free_slot(args.save.parent)
            print(json.dumps(add(args.save, slot, _decoder(args.decoder), dry_run=args.dry_run), indent=2))
        return 0
    except (SaveError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
