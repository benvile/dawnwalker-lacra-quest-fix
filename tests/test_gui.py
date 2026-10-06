import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from dawnwalker_lacra.gui import Window, default_save_folder


def test_game_date_is_displayed_with_clock_colons():
    assert Window.format_date("2026.10.06-04.23.55") == "2026.10.06-04:23:55"
    assert Window.format_date("unexpected") == "unexpected"
    assert Window.format_date(None) == "-"


def test_default_save_folder_uses_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_save_folder() == tmp_path / "Dawnwalker" / "Saved" / "SaveGames"


def test_background_analysis_reports_result():
    configured = os.environ.get("LACRA_TEST_SAVE_DIR")
    if not configured:
        pytest.skip("LACRA_TEST_SAVE_DIR is not configured")
    folder = Path(configured)
    if not folder.is_dir():
        pytest.skip("configured private save directory is unavailable")
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.path.setText(str(folder))
    window.refresh()
    row = next(
        row for row in range(window.table.rowCount())
        if window.table.item(row, 0).text() == "ManualSave23"
    )
    window.table.selectRow(row)
    window.analyze_selected()
    deadline = time.monotonic() + 5
    while (window.status.text() == "Analyzing save…" or window.workers) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.status.text() == "Tested release-Nish branch detected"
    assert window.table.item(row, 6).text() == "repair available"
    assert not window.workers
    window.close()
