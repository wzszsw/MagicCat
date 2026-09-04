"""导入/导出 UI（M5）：进度对话框 + 取消，全部在后台线程执行。

跨线程进度：工作线程通过 _Bus 信号对象 emit，Qt 自动排队回主线程更新。
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from magiccat.services import transfer
from magiccat.services.connection_service import ConnectionService
from magiccat.services.metadata_service import MetadataService
from magiccat.services.query_service import QueryService
from magiccat.ui.job import run_async

_FMT_FILTERS = "CSV 文件 (*.csv);;Excel 工作簿 (*.xlsx);;JSON 文件 (*.json);;SQL 脚本 (*.sql)"
_SYSTEM_SCHEMAS = {"information_schema", "performance_schema", "mysql", "sys"}


class _Bus(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    error = Signal(str)


def run_export(parent: QWidget, profile, schema: str, table: str,
               data, metadata: MetadataService, where: str | None = None) -> None:
    """导出当前表 → 文件（QFileDialog + 进度/取消）。where 透传给查询（与视图筛选一致）。"""
    path_text, _filter = QFileDialog.getSaveFileName(
        parent, "导出表数据", f"{schema}.{table}", _FMT_FILTERS)
    if not path_text:
        return
    path = Path(path_text)
    suffix = path.suffix.lower().lstrip(".")
    if suffix not in ("csv", "xlsx", "json", "sql"):
        # 用户未输扩展名：从所选过滤器补全
        path = path.with_suffix("." + _filter.split("(")[0].split()[-1].lower())
    fmt = path.suffix.lower().lstrip(".")

    bus = _Bus()
    cancel_event = threading.Event()
    dialog = QProgressDialog("准备导出…", "取消", 0, 100, parent)
    dialog.setWindowTitle(f"导出 {schema}.{table}")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(300)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.canceled.connect(cancel_event.set)
    dialog.setValue(0)

    def on_progress(done: int, total: int, msg: str) -> None:
        if total > 0:
            dialog.setMaximum(max(total, 1))
        dialog.setValue(done)
        dialog.setLabelText(msg)

    def on_finished(result: dict) -> None:
        dialog.close()
        if result.get("cancelled"):
            QMessageBox.information(parent, "导出", f"已取消（已导出 {result['rows']} 行）。")
        else:
            QMessageBox.information(
                parent, "导出", f"导出完成：{result['rows']} 行 →\n{result['path']}")

    def on_error(err: str) -> None:
        dialog.close()
        QMessageBox.critical(parent, "导出失败", err)

    bus.progress.connect(on_progress)
    bus.finished.connect(on_finished)
    bus.error.connect(on_error)
    run_async(
        lambda: transfer.export_table(profile, schema, table, path, fmt, data, metadata,
                                      where=where or "", progress=bus.progress.emit,
                                      cancel=cancel_event),
        lambda result: bus.finished.emit(result),
        lambda err: bus.error.emit(err))


class ImportCsvDialog(QDialog):
    """导入 CSV → 表。"""

    def __init__(self, connections: ConnectionService,
                 metadata: MetadataService, parent=None) -> None:
        super().__init__(parent)
        self._connections = connections
        self._metadata = metadata
        self._query = QueryService(connections)
        self.setWindowTitle("导入 CSV 到表")
        self.setMinimumWidth(480)
        self._bus = _Bus()
        self._cancel_event = threading.Event()
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
        self.table_combo = QComboBox()
        self.schema_combo.setEnabled(False)
        self.table_combo.setEnabled(False)

        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("选择 CSV 文件…")
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse)
        file_row.addWidget(self.file_edit)
        file_row.addWidget(btn_browse)

        self.header_check = QCheckBox("首行包含列名")
        self.header_check.setChecked(True)
        self.null_check = QCheckBox("空单元格导入为 NULL（可空列）")
        self.null_check.setChecked(True)

        form.addRow("连接", self.profile_combo)
        form.addRow("数据库", self.schema_combo)
        form.addRow("表", self.table_combo)
        form.addRow("CSV 文件", file_row)
        form.addRow("", self.header_check)
        form.addRow("", self.null_check)
        root.addLayout(form)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("")
        root.addWidget(self.progress_bar)
        root.addWidget(self.status_label)

        buttons = QDialogButtonBox()
        self.btn_start = buttons.addButton("开始导入", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Close)
        buttons.accepted.connect(self._start)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._buttons = buttons

        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self.schema_combo.currentIndexChanged.connect(self._on_schema_changed)

    # ---- 装载 ----
    def _populate_profiles(self) -> None:
        from magiccat.ui.profile_combo import populate_profile_combo

        populate_profile_combo(self.profile_combo, self._connections.profiles)

    def _current_profile(self):
        pid = self.profile_combo.currentData()
        return self._connections.get(pid) if pid else None

    def _on_profile_changed(self) -> None:
        profile = self._current_profile()
        self.schema_combo.clear()
        self.schema_combo.setEnabled(False)
        if profile is None:
            return
        try:
            dbs = [d["name"] for d in self._metadata.databases(profile)
                   if d["name"] not in _SYSTEM_SCHEMAS]
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"读取数据库失败：{exc}")
            return
        self.schema_combo.addItems(dbs)
        self.schema_combo.setEnabled(True)

    def _on_schema_changed(self) -> None:
        profile = self._current_profile()
        schema = self.schema_combo.currentText()
        self.table_combo.clear()
        self.table_combo.setEnabled(False)
        if profile is None or not schema:
            return
        try:
            tables = [t["name"] for t in self._metadata.tables(profile, schema)
                      if t["type"] == "BASE TABLE"]
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"读取表失败：{exc}")
            return
        self.table_combo.addItems(tables)
        self.table_combo.setEnabled(True)

    def _browse(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, "选择 CSV 文件", "", "CSV 文件 (*.csv);;所有文件 (*)")
        if path:
            self.file_edit.setText(path)

    # ---- 执行 ----
    def _start(self) -> None:
        profile = self._current_profile()
        schema = self.schema_combo.currentText()
        table = self.table_combo.currentText()
        path = self.file_edit.text().strip()
        if not (profile and schema and table):
            self.status_label.setText("请选择连接/库/表")
            return
        if not path:
            self.status_label.setText("请选择 CSV 文件")
            return
        self.btn_start.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("正在导入…")
        run_async(
            lambda: transfer.import_csv(
                profile, schema, table, path, self._query, self._metadata,
                has_header=self.header_check.isChecked(),
                empty_as_null=self.null_check.isChecked(),
                progress=self._bus.progress.emit, cancel=self._cancel_event),
            lambda result: self._bus.finished.emit(result),
            lambda err: self._bus.error.emit(err))

    def _on_progress(self, done: int, _total: int, msg: str) -> None:
        self.status_label.setText(msg)
        if _total > 0:
            self.progress_bar.setRange(0, max(_total, 1))
            self.progress_bar.setValue(done)

    def _on_finished(self, result: dict) -> None:
        self.btn_start.setEnabled(True)
        self.progress_bar.setRange(0, 1)
        if result.get("cancelled"):
            QMessageBox.information(self, "导入", f"已取消（已导入 {result['rows']} 行）。")
        elif result.get("first_error"):
            QMessageBox.critical(self, "导入", f"导入中止：{result['first_error']}")
        else:
            QMessageBox.information(self, "导入", f"导入完成：{result['rows']} 行")
            self.accept()

    def _on_error(self, err: str) -> None:
        self.btn_start.setEnabled(True)
        self.progress_bar.setRange(0, 1)
        QMessageBox.critical(self, "导入失败", err)


class CopyTableDialog(QDialog):
    """数据传输：同连接内复制表（结构 + 数据）。"""

    def __init__(self, connections: ConnectionService,
                 metadata: MetadataService, parent=None) -> None:
        super().__init__(parent)
        self._connections = connections
        self._metadata = metadata
        self.setWindowTitle("复制表（数据传输）")
        self.setMinimumWidth(500)
        self._bus = _Bus()
        self._cancel = threading.Event()
        self._bus.progress.connect(self._on_progress)
        self._bus.finished.connect(self._on_finished)
        self._bus.error.connect(self._on_error)
        self._build_ui()
        self._populate_profiles()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.profile_combo = QComboBox()
        self.src_schema_combo = QComboBox()
        self.src_table_combo = QComboBox()
        self.dst_schema_combo = QComboBox()
        self.dst_table_edit = QLineEdit()
        self.dst_table_edit.setPlaceholderText("目标表名（默认同源表名）")
        self.structure_check = QCheckBox("同时复制结构（CREATE TABLE IF NOT EXISTS dst LIKE src）")
        self.structure_check.setChecked(True)
        for c in (self.src_schema_combo, self.src_table_combo,
                  self.dst_schema_combo):
            c.setEnabled(False)
        form.addRow("连接", self.profile_combo)
        form.addRow("源数据库", self.src_schema_combo)
        form.addRow("源表", self.src_table_combo)
        form.addRow("目标数据库", self.dst_schema_combo)
        form.addRow("目标表", self.dst_table_edit)
        form.addRow("", self.structure_check)
        root.addLayout(form)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("")
        root.addWidget(self.progress_bar)
        root.addWidget(self.status_label)

        buttons = QDialogButtonBox()
        self.btn_start = buttons.addButton("开始复制", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Close)
        buttons.accepted.connect(self._start)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self.src_schema_combo.currentIndexChanged.connect(self._on_schema_changed)

    def _populate_profiles(self) -> None:
        from magiccat.ui.profile_combo import populate_profile_combo

        populate_profile_combo(self.profile_combo, self._connections.profiles)

    def _current_profile(self):
        pid = self.profile_combo.currentData()
        return self._connections.get(pid) if pid else None

    def _on_profile_changed(self) -> None:
        profile = self._current_profile()
        for combo in (self.src_schema_combo, self.dst_schema_combo):
            combo.clear()
            combo.setEnabled(False)
        self.src_table_combo.clear()
        self.src_table_combo.setEnabled(False)
        if profile is None:
            return
        try:
            dbs = [d["name"] for d in self._metadata.databases(profile)
                   if d["name"] not in _SYSTEM_SCHEMAS]
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"读取数据库失败：{exc}")
            return
        self.src_schema_combo.addItems(dbs)
        self.dst_schema_combo.addItems(dbs)
        for combo in (self.src_schema_combo, self.dst_schema_combo):
            combo.setEnabled(True)

    def _on_schema_changed(self) -> None:
        profile = self._current_profile()
        schema = self.src_schema_combo.currentText()
        self.src_table_combo.clear()
        self.src_table_combo.setEnabled(False)
        if profile is None or not schema:
            return
        try:
            tables = [t["name"] for t in self._metadata.tables(profile, schema)
                      if t["type"] == "BASE TABLE"]
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"读取表失败：{exc}")
            return
        self.src_table_combo.addItems(tables)
        self.src_table_combo.setEnabled(True)

    def _start(self) -> None:
        profile = self._current_profile()
        src_schema = self.src_schema_combo.currentText()
        src_table = self.src_table_combo.currentText()
        dst_schema = self.dst_schema_combo.currentText()
        dst_table = self.dst_table_edit.text().strip() or src_table
        if not (profile and src_schema and src_table and dst_schema and dst_table):
            self.status_label.setText("请选择 源库/源表 与 目标库/目标表")
            return
        from magiccat.services.data_service import DataService
        from magiccat.services.query_service import QueryService

        self.btn_start.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("正在复制…")
        data = DataService(self._connections)
        query = QueryService(self._connections)
        run_async(
            lambda: transfer.copy_table_data(
                profile, src_schema, src_table, dst_schema, dst_table,
                query, data, self._metadata,
                with_structure=self.structure_check.isChecked(),
                progress=self._bus.progress.emit, cancel=self._cancel),
            lambda result: self._bus.finished.emit(result),
            lambda err: self._bus.error.emit(err))

    def _on_progress(self, done: int, total: int, msg: str) -> None:
        self.status_label.setText(msg)
        if total > 0:
            self.progress_bar.setRange(0, max(total, 1))
            self.progress_bar.setValue(done)

    def _on_finished(self, result: dict) -> None:
        self.btn_start.setEnabled(True)
        self.progress_bar.setRange(0, 1)
        if result.get("cancelled"):
            QMessageBox.information(self, "复制", f"已取消（已复制 {result['rows']} 行）。")
        else:
            QMessageBox.information(self, "复制", f"复制完成：{result['rows']} 行")
            self.accept()

    def _on_error(self, err: str) -> None:
        self.btn_start.setEnabled(True)
        self.progress_bar.setRange(0, 1)
        QMessageBox.critical(self, "复制失败", err)
