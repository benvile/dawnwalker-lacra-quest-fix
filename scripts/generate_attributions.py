"""Generate readable third-party notices from Qt attribution metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("source", type=Path)
    result.add_argument("output", type=Path)
    result.add_argument("--title", required=True)
    result.add_argument("--module", action="append", default=[])
    result.add_argument("--include-segment", action="append", default=[])
    return result


def values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def main() -> int:
    args = parser().parse_args()
    modules = {module.casefold() for module in args.module}
    records: list[tuple[str, Path, dict[str, object]]] = []
    for metadata_path in args.source.rglob("qt_attribution.json"):
        relative = metadata_path.relative_to(args.source).as_posix()
        if args.include_segment and not any(
            segment.casefold() in relative.casefold() for segment in args.include_segment
        ):
            continue
        data = json.loads(metadata_path.read_text(encoding="utf-8"), strict=False)
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            module = str(entry.get("QDocModule", "")).casefold()
            if modules and module not in modules:
                continue
            name = str(entry.get("Name") or entry.get("Id") or relative)
            records.append((name.casefold(), metadata_path, entry))

    lines = [args.title, "=" * len(args.title), ""]
    lines.append(
        "Generated from the qt_attribution.json metadata in the exact upstream source "
        "archives listed in SOURCE_MANIFEST.md."
    )
    lines.append("")
    for _, metadata_path, entry in sorted(records):
        name = str(entry.get("Name") or entry.get("Id") or "Unnamed component")
        lines.extend([name, "-" * len(name)])
        for key in (
            "Id",
            "QDocModule",
            "QtUsage",
            "Description",
            "Homepage",
            "Version",
            "DownloadLocation",
            "License",
            "LicenseId",
        ):
            item_values = values(entry.get(key))
            if item_values:
                lines.append(f"{key}: {'; '.join(item_values)}")
        copyright_lines = values(entry.get("Copyright"))
        if copyright_lines:
            lines.append("Copyright:")
            lines.extend(f"  {item}" for item in copyright_lines)

        license_files = values(entry.get("LicenseFile")) + values(entry.get("LicenseFiles"))
        for license_name in license_files:
            license_path = metadata_path.parent / license_name
            if license_path.is_file():
                lines.extend(["", f"License file: {license_name}", ""])
                lines.append(license_path.read_text(encoding="utf-8", errors="replace").strip())
        lines.extend(["", "=" * 79, ""])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} attribution records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
