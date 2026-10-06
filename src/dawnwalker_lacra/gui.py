"""Small PySide6 GUI over the same inspected and transactional core as the CLI."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .core import PyOozDecoder, Save, analyze
from .slots import add, first_free_slot, patch_in_place, scan


def default_save_folder() -> Path:
    """Return Dawnwalker's normal per-user save directory on Windows."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "Dawnwalker" / "Saved" / "SaveGames"


def resource_path(*parts: str) -> Path:
    """Resolve bundled assets both from source and from a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base.joinpath(*parts)


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, operation: Callable[[], object]):
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.succeeded.emit(self.operation())
        except Exception as exc:  # noqa: BLE001 - worker boundary reports all failures to the UI
            self.signals.failed.emit(str(exc))
        finally:
            self.signals.finished.emit()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dawnwalker - Lacra Quest Fix")
        self.resize(980, 620)
        self.pool = QThreadPool.globalInstance()
        # Keep Python wrappers alive until their queued result signals reach the UI thread.
        self.workers: dict[int, Worker] = {}
        self.folder = default_save_folder()
        self.path = QLineEdit()
        self.path.setText(str(self.folder))
        self.path.setPlaceholderText("Select a SaveGames directory or a copy")
        browse = QPushButton("Choose folder…")
        browse.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        browse.clicked.connect(self.choose_folder)
        refresh = QPushButton("Refresh")
        refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        refresh.clicked.connect(self.refresh)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        path_row.addWidget(refresh)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Slot", "Date", "Play time", "Day", "Build", "Thumbnail", "Status"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.show_thumbnail)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.preview = QLabel("No thumbnail")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(QSize(320, 180))
        self.preview.setMaximumHeight(220)

        analyze_button = QPushButton("Analyze selected save")
        analyze_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView)
        )
        analyze_button.clicked.connect(self.analyze_selected)
        add_button = QPushButton("Create repaired copy (ADD)")
        add_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        add_button.clicked.connect(self.add_selected)
        patch_button = QPushButton("Repair in place (PATCH)…")
        patch_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton))
        patch_button.clicked.connect(self.patch_selected)
        open_button = QPushButton("Open folder")
        open_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        open_button.clicked.connect(self.open_folder)
        buttons = QHBoxLayout()
        for button in (analyze_button, add_button, patch_button, open_button):
            buttons.addWidget(button)

        self.status = QLabel("Choose a folder. The game must be closed before writing saves.")
        layout = QVBoxLayout()
        layout.addLayout(path_row)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.preview)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        try:
            default_folder_exists = self.folder.is_dir()
        except OSError:
            default_folder_exists = False
        if default_folder_exists:
            default_folder = self.folder
            QTimer.singleShot(
                0,
                lambda: self.refresh()
                if Path(self.path.text().strip()) == default_folder
                else None,
            )

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select save directory", str(self.folder))
        if selected:
            self.path.setText(selected)
            self.refresh()

    def refresh(self) -> None:
        try:
            self.folder = Path(self.path.text().strip())
            slots = scan(self.folder)
            self.table.setRowCount(0)
            for slot in slots:
                sav = self.folder / f"ManualSave{slot}.sav"
                meta_path = sav.with_suffix(".meta")
                meta, status = {}, "Not analyzed"
                if meta_path.is_file():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8-sig")).get("Meta", {})
                    except (OSError, json.JSONDecodeError):
                        status = "Broken metadata"
                else:
                    status = "Missing metadata"
                values = [
                    f"ManualSave{slot}",
                    self.format_date(meta.get("Date")),
                    self.format_play_time(meta.get("PlayTime")),
                    str(meta.get("Day", "-")),
                    str(meta.get("BuildVersion", "-")),
                    "Yes" if sav.with_suffix(".png").is_file() else "No",
                    status,
                ]
                row = self.table.rowCount()
                self.table.insertRow(row)
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, str(sav))
                    self.table.setItem(row, column, item)
            self.status.setText(f"Found {len(slots)} manual saves; first free slot: {first_free_slot(self.folder)}")
        except Exception as exc:  # noqa: BLE001 - folder errors must remain in the GUI
            QMessageBox.critical(self, "Cannot read folder", str(exc))

    @staticmethod
    def format_play_time(value) -> str:
        if not isinstance(value, int):
            return "-"
        hours, remainder = divmod(value, 3600)
        minutes = remainder // 60
        return f"{hours}:{minutes:02d}"

    @staticmethod
    def format_date(value) -> str:
        if not isinstance(value, str):
            return "-"
        match = re.fullmatch(r"(\d{4}\.\d{2}\.\d{2})-(\d{2})\.(\d{2})\.(\d{2})", value)
        if not match:
            return value
        date, hour, minute, second = match.groups()
        return f"{date}-{hour}:{minute}:{second}"

    def selected_save(self) -> Path | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Select a save", "Select one ManualSave row first.")
            return None
        return Path(self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole))

    def run_worker(self, label: str, operation: Callable[[], object], done: Callable[[object], None]) -> None:
        self.status.setText(label)
        worker = Worker(operation)
        token = id(worker)
        self.workers[token] = worker
        worker.signals.succeeded.connect(done)
        worker.signals.failed.connect(self.worker_failed)
        worker.signals.finished.connect(lambda: self.workers.pop(token, None))
        self.pool.start(worker)

    def worker_failed(self, message: str) -> None:
        self.status.setText("Operation failed")
        QMessageBox.critical(self, "Operation failed", message)

    def analyze_selected(self) -> None:
        sav = self.selected_save()
        if sav is None:
            return

        def operation():
            return analyze(Save.from_path(sav, PyOozDecoder()))

        def done(result):
            row = self.table.currentRow()
            self.table.item(row, 6).setText(result.status.replace("_", " "))
            self.status.setText(result.reason)

        self.run_worker("Analyzing save…", operation, done)

    def add_selected(self) -> None:
        sav = self.selected_save()
        if sav is None:
            return
        slot = first_free_slot(self.folder)
        answer = QMessageBox.question(
            self, "Create repaired copy",
            f"Create ManualSave{slot} from {sav.stem}?\n\nThe source will not be changed.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def done(report):
            self.status.setText(f"Created {report['target']} and validated the result")
            self.refresh()

        self.run_worker("Creating and validating repaired copy…",
                        lambda: add(sav, slot, PyOozDecoder()), done)

    def patch_selected(self) -> None:
        sav = self.selected_save()
        if sav is None:
            return
        answer = QMessageBox.warning(
            self, "Repair in place",
            f"Repair {sav.stem} in place?\n\nA verified backup and recovery manifest will be created first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def done(report):
            self.status.setText(f"Patched {sav.stem}; backup: {report['backup']}")
            QMessageBox.information(self, "Repair complete", self.status.text())
            self.refresh()

        self.run_worker("Backing up, repairing and validating…",
                        lambda: patch_in_place(sav, PyOozDecoder()), done)

    def show_thumbnail(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.preview.setText("No thumbnail")
            self.preview.setPixmap(QPixmap())
            return
        sav = Path(self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole))
        png = sav.with_suffix(".png")
        pixmap = QPixmap(str(png)) if png.is_file() else QPixmap()
        if pixmap.isNull():
            self.preview.setText("No usable thumbnail")
            self.preview.setPixmap(QPixmap())
        else:
            self.preview.setText("")
            self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))

    def open_folder(self) -> None:
        if self.folder.is_dir():
            try:
                os.startfile(self.folder.resolve())
            except OSError as exc:
                QMessageBox.critical(self, "Cannot open folder", str(exc))


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    application = QApplication(sys.argv)
    application.setWindowIcon(QIcon(str(resource_path("assets", "app-icon.png"))))
    window = Window()
    smoke_test = "--smoke-test" in sys.argv or os.environ.get("LACRA_SMOKE_TEST") == "1"
    if smoke_test:
        index = sys.argv.index("--smoke-test") if "--smoke-test" in sys.argv else -1
        folder = (sys.argv[index + 1] if index >= 0 and index + 1 < len(sys.argv)
                  else os.environ.get("LACRA_SMOKE_FOLDER"))
        if folder:
            window.path.setText(folder)
            window.refresh()
        smoke_save = os.environ.get("LACRA_SMOKE_SAVE")
        if smoke_save:
            operation = lambda: analyze(Save.from_path(Path(smoke_save), PyOozDecoder()))
            if os.environ.get("LACRA_SMOKE_BACKGROUND") == "1":
                exit_code = [2]

                def done(result):
                    exit_code[0] = 0 if result.status in {"repair_available", "already_progressed"} else 1
                    application.quit()

                window.run_worker("Analyzing save…", operation, done)
                QTimer.singleShot(5000, application.quit)
                application.exec()
                window.close()
                return exit_code[0]
            result = operation()
            if result.status not in {"repair_available", "already_progressed"}:
                raise RuntimeError(f"Packaged decoder smoke test failed: {result.reason}")
        application.processEvents()
        window.close()
        return 0
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
