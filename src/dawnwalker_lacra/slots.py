"""Save slot discovery and safe ADD transaction."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from . import profile
from .core import Decoder, Save, repair, require

SLOT = re.compile(r"^ManualSave(\d+)\.sav$", re.IGNORECASE)


def scan(folder: Path) -> list[int]:
    require(folder.is_dir(), f"Save directory not found: {folder}")
    return sorted(int(match.group(1)) for path in folder.iterdir()
                  if (match := SLOT.match(path.name)))


def first_free_slot(folder: Path) -> int:
    require(folder.is_dir(), f"Save directory not found: {folder}")
    used = set()
    for path in folder.iterdir():
        match = re.match(r"^ManualSave(\d+)\.(sav|meta|png)$", path.name, re.IGNORECASE)
        if match:
            used.add(int(match.group(1)))
    slot = 0
    while slot in used:
        slot += 1
    return slot


def add(source_sav: Path, slot: int, decoder: Decoder | None = None,
        now: datetime | None = None, dry_run: bool = False) -> dict:
    require(slot >= 0, "Slot must be non-negative")
    folder = source_sav.parent
    source_meta = source_sav.with_suffix(".meta")
    require(source_sav.is_file() and source_meta.is_file(), "Source .sav/.meta pair is incomplete")
    stem = f"ManualSave{slot}"
    targets = [folder / f"{stem}.sav", folder / f"{stem}.meta", folder / f"{stem}.png"]
    require(not any(path.exists() for path in targets), f"Target slot {stem} already has files")
    save = Save.from_path(source_sav, decoder)
    output, report = repair(save)
    meta = json.loads(source_meta.read_text(encoding="utf-8-sig"))
    require(isinstance(meta.get("Meta"), dict), "Invalid .meta document")
    _validate_meta(meta["Meta"], source_sav.stem)
    meta["Meta"]["SaveName"] = stem
    meta["Meta"]["Date"] = (now or datetime.now().astimezone()).strftime("%Y.%m.%d-%H.%M.%S")
    report.update({"mode": "add", "source": source_sav.name, "target": stem, "dry_run": dry_run})
    if dry_run:
        return report
    source_png = source_sav.with_suffix(".png")
    with tempfile.TemporaryDirectory(prefix="lacra-add-", dir=folder) as staging_name:
        staging = Path(staging_name)
        (staging / targets[0].name).write_bytes(output)
        (staging / targets[1].name).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if source_png.is_file():
            shutil.copy2(source_png, staging / targets[2].name)
        # Publish only after all staged files exist and the generated save parses again.
        Save.from_path(staging / targets[0].name)
        published = []
        try:
            for target in targets:
                staged = staging / target.name
                if staged.exists():
                    os.link(staged, target)
                    staged.unlink()
                    published.append(target)
        except Exception:
            for target in published:
                target.unlink(missing_ok=True)
            raise
    return report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_meta(meta: dict, stem: str) -> None:
    require(meta.get("SaveName") == stem, "Meta.SaveName does not match the source slot")
    require(meta.get("SaveVersion") in profile.SUPPORTED_SAVE_VERSIONS
            and meta.get("GameVersion") == profile.SUPPORTED_GAME_VERSION,
            "Unsupported save metadata version")
    require(meta.get("BuildVersion") == profile.SUPPORTED_BUILD_VERSION,
            "Unsupported game build metadata")


def _write_manifest(path: Path, value: dict) -> None:
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(pending, path)


def patch_in_place(source_sav: Path, decoder: Decoder | None = None,
                   now: datetime | None = None, dry_run: bool = False) -> dict:
    """Repair one slot in place with a verified backup and recoverable journal."""
    folder = source_sav.parent
    source_meta = source_sav.with_suffix(".meta")
    source_png = source_sav.with_suffix(".png")
    require(source_sav.is_file() and source_meta.is_file(), "Source .sav/.meta pair is incomplete")
    save = Save.from_path(source_sav, decoder)
    output, report = repair(save)
    meta = json.loads(source_meta.read_text(encoding="utf-8-sig"))
    require(isinstance(meta.get("Meta"), dict), "Invalid .meta document")
    _validate_meta(meta["Meta"], source_sav.stem)
    meta["Meta"]["Date"] = (now or datetime.now().astimezone()).strftime("%Y.%m.%d-%H.%M.%S")
    report.update({"mode": "patch", "source": source_sav.name, "target": source_sav.stem,
                   "dry_run": dry_run})
    if dry_run:
        return report

    operation = f"{datetime.now().astimezone():%Y%m%d-%H%M%S}-{source_sav.stem}-{uuid.uuid4().hex[:8]}"
    backup = folder / ".lacra-backups" / operation
    backup.mkdir(parents=True, exist_ok=False)
    originals = [source_sav, source_meta] + ([source_png] if source_png.is_file() else [])
    hashes = {}
    for original in originals:
        destination = backup / original.name
        shutil.copy2(original, destination)
        hashes[original.name] = _sha256(original)
        require(_sha256(destination) == hashes[original.name], f"Backup verification failed: {original.name}")
    manifest = {
        "operation": operation,
        "state": "backed_up",
        "slot_directory": str(folder.resolve()),
        "files": hashes,
        "restore": f'dawnwalker-lacra recover "{backup}"',
    }
    manifest_path = backup / "manifest.json"
    _write_manifest(manifest_path, manifest)
    (backup / "RESTORE.txt").write_text(
        "Close the game, then run:\n" + manifest["restore"] + "\n", encoding="utf-8"
    )
    with tempfile.TemporaryDirectory(prefix="lacra-patch-", dir=folder) as staging_name:
        staging = Path(staging_name)
        staged_sav = staging / source_sav.name
        staged_meta = staging / source_meta.name
        staged_sav.write_bytes(output)
        staged_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        Save.from_path(staged_sav)
        manifest["state"] = "replacing"
        _write_manifest(manifest_path, manifest)
        try:
            os.replace(staged_sav, source_sav)
            os.replace(staged_meta, source_meta)
        except Exception:
            _restore_files(backup, folder, hashes)
            manifest["state"] = "rolled_back"
            _write_manifest(manifest_path, manifest)
            raise
    manifest["state"] = "completed"
    manifest["output_sha256"] = _sha256(source_sav)
    _write_manifest(manifest_path, manifest)
    report["backup"] = str(backup)
    return report


def _restore_files(backup: Path, folder: Path, hashes: dict[str, str]) -> None:
    for name, expected in hashes.items():
        saved = backup / name
        require(saved.is_file() and _sha256(saved) == expected, f"Invalid backup file: {name}")
    with tempfile.TemporaryDirectory(prefix="lacra-restore-", dir=folder) as staging_name:
        staging = Path(staging_name)
        for name in hashes:
            shutil.copy2(backup / name, staging / name)
        for name in hashes:
            os.replace(staging / name, folder / name)


def recover(backup: Path) -> dict:
    manifest_path = backup / "manifest.json"
    require(manifest_path.is_file(), "Backup manifest not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(isinstance(manifest.get("files"), dict), "Invalid backup manifest")
    folder = Path(manifest["slot_directory"])
    require(folder.is_dir(), "Original slot directory is unavailable")
    _restore_files(backup, folder, manifest["files"])
    manifest["state"] = "restored"
    _write_manifest(manifest_path, manifest)
    return {"restored": sorted(manifest["files"]), "directory": str(folder)}
