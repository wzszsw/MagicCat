"""计划任务管理对话框：任务增删、启停、立即执行（备份类）。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
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
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from magiccat.services.connection_service import ConnectionService
from magiccat.services.metadata_service import MetadataService
from magiccat.services.tasks import Task, TaskStore
from magiccat.ui.job import run_async

_SYSTEM_SCHEMAS = {"information_schema", "performance_schema", "mysql", "sys"}


class _Bus(QObject):
    finished = Signal(str, object)  # (status_text, error|None)
    refresh = Signal()


class TaskDialog(QDialog):
    def __init__(self, connections: ConnectionService, metadata: MetadataService,
                 store: TaskStore | None = None, parent=None) -> None:
        super().__init__(parent)
        self._connections = connections
        self._metadata = metadata
        self._store = store or TaskStore.default()
        self._bus = _Bus()
        self._bus.finished.connect(self._on_run_done)
        self.setWindowTitle("计划任务（应用运行期间执行）")
        self.resize(640, 420)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("任务将仅在 MagicCat 运行期间按间隔自动执行（备份到目录）。"))
        self.list_widget = QListWidget()
        root.addWidget(self.list_widget, 1)

        bar = QHBoxLayout()
        btn_add = QPushButton("新增任务…")
        btn_delete = QPushButton("删除")
        btn_toggle = QPushButton("启用/停用")
        btn_run = QPushButton("立即执行")
        for b in (btn_add, btn_delete, btn_toggle, btn_run):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        root.addWidget(buttons)

        btn_add.clicked.connect(self._add)
        btn_delete.clicked.connect(self._delete)
        btn_toggle.clicked.connect(self._toggle)
        btn_run.clicked.connect(self._run_now)
        self._tasks = self._store.load()
        self._refresh()

    # ---- 列表 ----
    def _refresh(self) -> None:
        self.list_widget.clear()
        for t in self._tasks:
            flag = "●" if t.enabled else "○"
            self.list_widget.addItem(QListWidgetItem(
                f"{flag} {t.name} · {t.schema} · 每 {t.interval_min} 分钟"
                + (f" · {t.last_status[:60]}" if t.last_status else "")))
        self.list_widget.setCurrentRow(max(0, self.list_widget.count() - 1))

    def _current(self) -> Task | None:
        row = self.list_widget.currentRow()
        return self._tasks[row] if 0 <= row < len(self._tasks) else None

    # ---- 编辑 ----
    def _add(self) -> None:
        dialog = _TaskEditDialog(self._connections, self._metadata, self)
        if dialog.exec():
            self._tasks.append(dialog.task())
            self._store.save(self._tasks)
            self._refresh()

    def _delete(self) -> None:
        task = self._current()
        if task is None:
            return
        if QMessageBox.question(self, "删除任务", f"删除任务「{task.name}」？",
                                ) == QMessageBox.Yes:
            self._tasks = [t for t in self._tasks if t.id != task.id]
            self._store.save(self._tasks)
            self._refresh()

    def _toggle(self) -> None:
        task = self._current()
        if task:
            task.enabled = not task.enabled
            self._store.save(self._tasks)
            self._refresh()

    # ---- 立即执行 ----
    def _run_now(self) -> None:
        task = self._current()
        profile = self._connections.get(task.profile_id) if task else None
        if task is None or profile is None:
            QMessageBox.information(self, "立即执行", "请选择有效任务。")
            return
        # 先标记运行时间，避免调度器并发触发
        from magiccat.services.tasks import _now_iso

        task.last_run = _now_iso()
        self._store.save(self._tasks)
        run_async(
            lambda: self._do_run(task, profile),
            lambda text: self._bus.finished.emit(text, None),
            lambda err: self._bus.finished.emit(f"失败：{err}", err))

    def _do_run(self, task: Task, profile) -> str:
        from magiccat.services.tasks import run_backup_task

        return run_backup_task(task, profile, self._connections)

    def _on_run_done(self, status: str, error) -> None:
        task = self._current()
        if task is not None:
            task.last_status = status
            self._store.save(self._tasks)
        self._refresh()
        self.statusHint = status
        if error:
            QMessageBox.warning(self, "任务执行", status)
        else:
            QMessageBox.information(self, "任务执行", status)


class _TaskEditDialog(QDialog):
    def __init__(self, connections: ConnectionService, metadata: MetadataService,
                 parent=None) -> None:
        super().__init__(parent)
        self._connections = connections
        self._metadata = metadata
        self.setWindowTitle("新增计划任务")
        form = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("任务名称（用于备份文件名）")
        self.profile_combo = QComboBox()
        for p in connections.profiles:
            self.profile_combo.addItem(p.display_name, p.id)
        self.schema_combo = QComboBox()
        self.schema_combo.setEnabled(False)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 24 * 60)
        self.interval_spin.setValue(60)
        self.dir_edit = QLineEdit()
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(34)
        btn_browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.dir_edit, 1)
        row.addWidget(btn_browse)
        self.enable_check = QCheckBox("启用")
        self.enable_check.setChecked(True)
        form.addRow("名称", self.name_edit)
        form.addRow("连接", self.profile_combo)
        form.addRow("数据库", self.schema_combo)
        form.addRow("间隔(分钟)", self.interval_spin)
        form.addRow("备份目录", row)
        form.addRow("", self.enable_check)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.profile_combo.currentIndexChanged.connect(self._load_schemas)
        self._load_schemas()

    def _load_schemas(self) -> None:
        pid = self.profile_combo.currentData()
        profile = self._connections.get(pid) if pid else None
        self.schema_combo.clear()
        self.schema_combo.setEnabled(False)
        if profile is None:
            return
        try:
            dbs = [d["name"] for d in self._metadata.databases(profile)
                   if d["name"] not in _SYSTEM_SCHEMAS]
        except Exception:  # noqa: BLE001
            return
        self.schema_combo.addItems(dbs)
        self.schema_combo.setEnabled(True)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择备份目录")
        if path:
            self.dir_edit.setText(path)

    def _accept(self) -> None:
        if not self.name_edit.text().strip() or not self.dir_edit.text().strip():
            QMessageBox.information(self, "新增任务", "请填写名称与备份目录。")
            return
        self.accept()

    def task(self) -> Task:
        return Task(
            name=self.name_edit.text().strip(),
            kind="backup",
            profile_id=str(self.profile_combo.currentData()),
            schema=self.schema_combo.currentText(),
            interval_min=self.interval_spin.value(),
            target_dir=self.dir_edit.text().strip(),
            enabled=self.enable_check.isChecked(),
        )
