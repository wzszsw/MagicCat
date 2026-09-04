"""备份/恢复 UI（M6）：备份数据库为 .sql；执行 .sql 脚本恢复。"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from magiccat.services import backup
from magiccat.services.connection_service import ConnectionService
from magiccat.services.data_service import DataService
from magiccat.services.metadata_service import MetadataService
from magiccat.services.query_service import QueryService
from magiccat.ui.job import run_async

_SYSTEM_SCHEMAS = {"information_schema", "performance_schema", "mysql", "sys"}


class _Bus(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    error = Signal(str)


class BackupDialog(QDialog):
    """备份：连接+库 → 全部基础表 → 单个 .sql。"""

    def __init__(self, connections: ConnectionService,
                 metadata: MetadataService, parent=None) -> None:
        super().__init__(parent)
        self._connections = connections
        self._metadata = metadata
        self._data = DataService(connections)
        self.setWindowTitle("备份数据库为 SQL")
        self.setMinimumWidth(460)
        self._bus = _Bus()
        self._cancel = threading.Event()
        self._build_ui()
        self._bus.progress.connect(self._on_progress)
        self._bus.finished.connect(self._on_finished)
        self._bus.error.connect(self._on_error)
        self._populate_profiles()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.profile_combo = QComboBox()
        self.schema_combo = QComboBox()
        self.schema_combo.setEnabled(False)
        self.path_label = QLabel("未选择文件")
        self._path = ""
        form.addRow("连接", self.profile_combo)
        form.addRow("数据库", self.schema_combo)
        form.addRow("备份文件", self.path_label)
        root.addLayout(form)

        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.status = QLabel("")
        root.addWidget(self.bar)
        root.addWidget(self.status)

        buttons = QDialogButtonBox()
        self.btn_start = buttons.addButton("开始备份", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Close)
        buttons.accepted.connect(self._start)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)

    def _populate_profiles(self) -> None:
        from magiccat.ui.profile_combo import populate_profile_combo

        populate_profile_combo(self.profile_combo, self._connections.profiles)

    def _current_profile(self):
        pid = self.profile_combo.currentData()
        return self._connections.get(pid) if pid else None

    def _on_profile_changed(self) -> None:
        self.schema_combo.clear()
        profile = self._current_profile()
        if profile is None:
            return
        try:
            dbs = [d["name"] for d in self._metadata.databases(profile)
                   if d["name"] not in _SYSTEM_SCHEMAS]
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"读取数据库失败：{exc}")
            return
        self.schema_combo.addItems(dbs)
        self.schema_combo.setEnabled(True)

    def _browse(self) -> None:
        path, _f = QFileDialog.getSaveFileName(self, "备份到", "backup.sql",
                                               "SQL 脚本 (*.sql)")
        if path:
            self._path = path
            self.path_label.setText(str(path))

    def _start(self) -> None:
        profile = self._current_profile()
        schema = self.schema_combo.currentText()
        if not (profile and schema and self._path):
            self.status.setText("请选择连接/数据库/备份文件")
            return
        schema_, path = schema, self._path
        profile_ref = profile

        def fetch() -> dict:
            tables = [t["name"] for t in self._metadata.tables(profile_ref, schema_)
                      if t["type"] == "BASE TABLE"]
            if not tables:
                return {"tables": 0, "rows": 0, "cancelled": False, "empty": True}
            return backup.dump_tables_sql(
                profile_ref, schema_, tables, path, self._data, self._metadata,
                progress=self._bus.progress.emit, cancel=self._cancel)

        self.btn_start.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        run_async(fetch,
                  lambda r: self._bus.finished.emit(r),
                  lambda err: self._bus.error.emit(err))

    def _on_progress(self, done: int, total: int, msg: str) -> None:
        self.status.setText(msg)
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)

    def _on_finished(self, result: dict) -> None:
        self.btn_start.setEnabled(True)
        if result.get("empty"):
            QMessageBox.information(self, "备份", "该库没有基础表。")
            return
        if result.get("cancelled"):
            QMessageBox.information(self, "备份", "已取消。")
        else:
            QMessageBox.information(
                self, "备份",
                f"备份完成：{result['tables']} 张表 · {result['rows']} 行 →\n{self._path}")
            self.accept()

    def _on_error(self, err: str) -> None:
        self.btn_start.setEnabled(True)
        QMessageBox.critical(self, "备份失败", err)


def run_restore_script(parent, connections: ConnectionService,
                       metadata: MetadataService) -> None:
    """执行 .sql 脚本（如备份文件）：先选连接，再选文件。"""
    path, _f = QFileDialog.getOpenFileName(parent, "选择 SQL 脚本",
                                           "", "SQL 脚本 (*.sql);;所有文件 (*)")
    if not path:
        return
    from PySide6.QtWidgets import QInputDialog

    profiles = connections.profiles
    if not profiles:
        QMessageBox.information(parent, "恢复", "请先新增一个连接。")
        return
    names = [p.display_name for p in profiles]
    name, ok = QInputDialog.getItem(parent, "执行 SQL 脚本", "在哪个连接上执行？",
                                    names, 0, False)
    if not ok:
        return
    profile = profiles[names.index(name)]
    # 备份文件头含目标库：-- MagicCat 全库备份 · <schema>
    schema = None
    try:
        first_lines = Path(path).read_text(encoding="utf-8").splitlines()[:3]
        for line in first_lines:
            if "MagicCat 全库备份 · " in line:
                schema = line.split("· ", 1)[1].strip()
                break
    except OSError:
        pass
    dialog = QMessageBox(parent)
    dialog.setWindowTitle("执行 SQL 脚本")
    dialog.setIcon(QMessageBox.Information)
    dialog.setText("正在执行…")
    dialog.setStandardButtons(QMessageBox.NoButton)
    dialog.show()

    def done(result: dict) -> None:
        dialog.close()
        if result["ok"]:
            QMessageBox.information(
                parent, "执行 SQL 脚本",
                f"完成：{result['statements']} 条语句执行成功。")
        else:
            QMessageBox.warning(
                parent, "执行 SQL 脚本",
                f"{result['statements']} 条语句中 {len(result['errors'])} 条失败：\n"
                + "\n".join(result["errors"]))

    def error(err: str) -> None:
        dialog.close()
        QMessageBox.critical(parent, "执行 SQL 脚本", err)

    run_async(lambda: backup.restore_sql_file(profile, path, QueryService(connections),
                                              schema=schema),
              done, error)
