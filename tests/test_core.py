import os
from pathlib import Path

import pytest

from dawnwalker_lacra.core import PyOozDecoder, Save, SaveError, analyze, pack, packed, repair
from dawnwalker_lacra.slots import add, first_free_slot, patch_in_place, recover

ROOT = Path(__file__).parents[1]
PRIVATE = ROOT / ".private" / "poc90"


def private_save_dir() -> Path:
    configured = os.environ.get("LACRA_TEST_SAVE_DIR")
    if not configured:
        pytest.skip("LACRA_TEST_SAVE_DIR is not configured")
    folder = Path(configured)
    if not folder.is_dir():
        pytest.skip("configured private save directory is unavailable")
    return folder


@pytest.mark.parametrize("value", [0, 1, 127, 128, 65535, 65536, (4 << 16) | 3, 2**35 - 1])
def test_packed_round_trip(value):
    encoded = pack(value)
    assert packed(encoded, 0) == (value, len(encoded))


def test_packed_rejects_truncation():
    with pytest.raises(SaveError):
        packed(b"\x01", 0)


def test_game_verified_save_is_structurally_valid_and_progressed():
    path = PRIVATE / "ManualSave90.sav"
    if not path.exists():
        pytest.skip("private fixture unavailable")
    save = Save.from_path(path)
    assert save.sha256 == "f24bacd06b005f8a7b960b21db5889da9f1c4ced73b166ebf28d0660ac477d14"
    assert analyze(save).status == "already_progressed"


def test_footer_corruption_is_rejected():
    path = PRIVATE / "ManualSave90.sav"
    if not path.exists():
        pytest.skip("private fixture unavailable")
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    with pytest.raises(SaveError, match="footer"):
        Save(bytes(data))


def test_private_source_rebuilds_game_verified_result_exactly():
    source = private_save_dir() / "ManualSave23.sav"
    expected = PRIVATE / "ManualSave90.sav"
    if not source.exists() or not expected.exists():
        pytest.skip("private regression fixtures unavailable")
    result, report = repair(Save.from_path(source, PyOozDecoder()))
    assert result == expected.read_bytes()
    assert report["output_sha256"] == "f24bacd06b005f8a7b960b21db5889da9f1c4ced73b166ebf28d0660ac477d14"


@pytest.mark.parametrize("slot", [*range(12, 24), 27])
def test_post_bad_ending_ai_variants_are_eligible(slot):
    source = private_save_dir() / f"ManualSave{slot}.sav"
    if not source.exists():
        pytest.skip("private source unavailable")
    save = Save.from_path(source, PyOozDecoder())
    result = analyze(save)
    assert result.status == "repair_available"
    patched, _ = repair(save)
    assert analyze(Save(patched)).status == "already_progressed"


def _copy_source(tmp_path):
    source_dir = private_save_dir()
    for suffix in (".sav", ".meta", ".png"):
        source = source_dir / f"ManualSave23{suffix}"
        if source.exists():
            (tmp_path / source.name).write_bytes(source.read_bytes())
    return tmp_path / "ManualSave23.sav"


def test_add_keeps_source_and_creates_consistent_slot(tmp_path):
    source = _copy_source(tmp_path)
    original = source.read_bytes()
    result = add(source, 90, PyOozDecoder())
    assert source.read_bytes() == original
    assert Save.from_path(tmp_path / "ManualSave90.sav").sha256 == result["output_sha256"]
    assert '"SaveName": "ManualSave90"' in (tmp_path / "ManualSave90.meta").read_text()
    assert (tmp_path / "ManualSave90.png").is_file()
    with pytest.raises(SaveError, match="already has files"):
        add(source, 90, PyOozDecoder())


def test_patch_backup_and_recovery(tmp_path):
    source = _copy_source(tmp_path)
    original = source.read_bytes()
    result = patch_in_place(source, PyOozDecoder())
    assert source.read_bytes() != original
    backup = Path(result["backup"])
    assert (backup / "manifest.json").is_file()
    recover(backup)
    assert source.read_bytes() == original


def test_first_free_slot_reserves_orphan_components(tmp_path):
    (tmp_path / "ManualSave0.meta").write_text("{}")
    (tmp_path / "ManualSave1.png").write_bytes(b"png")
    assert first_free_slot(tmp_path) == 2
