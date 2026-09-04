"""SQL 转储 / 运行 SQL 文件 进度对话框（对标 Navicat）。

- 顶部统计：服务器 / 数据库 / 模式 / 转储到 / 已处理 / 错误 / 已传输 / 时间。
- 中部：日志视图（随进度追加行）。
- 底部：进度条 + 「打开…」/「关闭」按钮。
复用 transfer 的跨线程信号模式：工作线程发 progress/log/finished/error，Qt 排队回主线程。
适合与 backup.dump_schema_sql / restore_sql_file（含 ProgressCb）配合。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from magiccat.ui.job import run_async


class _Bus(QObject):
    progress = Signal(int, int, str)  # done, total, message
    log = Signal(str)                # 追加一条日志行
    finished = Signal(object)        # 结果 dict（含 cancelled/错误统计）
    error = Signal(str)              # 致命错误


class SqlProgressDialog(QDialog):
    """Navicat 风格 SQL 进度对话框。调用方先 set_meta()，再 start(fn, on_done)。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SQL 进度")
        self.setMinimumWidth(620)
        self.setMinimumHeight(480)
        self._bus = _Bus()
        self._cancel_event = threading.Event()
        self._t0 = 0.0
        self._done = 0
        self._errors = 0

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._meta_labels: dict[str, QLabel] = {}
        for key, text in (("server", "服务器"), ("database", "数据库"),
                          ("schema", "模式"), ("path", "转储到"),
                          ("done", "已处理"), ("errors", "错误"),
                          ("rows", "已传输"), ("elapsed", "时间")):
            label = QLabel("—")
            self._meta_labels[key] = label
            form.addRow(f"{text}：", label)
        root.addLayout(form)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        root.addWidget(self.log_view, 1)

        bottom = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        bottom.addWidget(self.progress_bar, 1)
        self.btn_open = QPushButton("打开…")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_path)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        bottom.addWidget(self.btn_open)
        bottom.addWidget(self.btn_close)
        root.addLayout(bottom)

        self._result_path: str | None = None
        self._bus.progress.connect(self._on_progress)
        self._bus.log.connect(self._append_log)
        self._bus.finished.connect(self._on_finished)
        self._bus.error.connect(self._on_error)

    # ---- 对外 ----
    def set_meta(self, server: str = "", database: str = "", schema: str = "",
                 path: str = "") -> None:
        self._result_path = path or None
        self._meta_labels["server"].setText(server or "—")
        self._meta_labels["database"].setText(database or "—")
        self._meta_labels["schema"].setText(schema or "—")
        self._meta_labels["path"].setText(path or "—")
        self._meta_labels["done"].setText("0")
        self._meta_labels["errors"].setText("0")
        self._meta_labels["rows"].setText("0")
        self._meta_labels["elapsed"].setText("0s")
        self.log_view.clear()

    def start(self, fn, on_done) -> None:
        """启动后台任务。fn() 在后台线程执行；返回 dict 供 on_done 收尾。"""
        self._t0 = time.time()
        self._bus.finished.connect(on_done)
        self.show()
        run_async(lambda: fn(self._bus, self._cancel_event),
                  lambda result: self._bus.finished.emit(result),
                  lambda err: self._bus.error.emit(err))

    # ---- 内部 ----
    def _on_progress(self, done: int, total: int, msg: str) -> None:
        self._done = done
        if total > 0:
            self.progress_bar.setMaximum(max(total, 1))
            self.progress_bar.setValue(done)
        self._meta_labels["done"].setText(f"{done}")
        self._meta_labels["elapsed"].setText(f"{time.time() - self._t0:.1f}s")
        if msg:
            self._append_log(msg)

    def _append_log(self, line: str) -> None:
        if line:
            self.log_view.appendPlainText(line)

    def _on_finished(self, res: dict) -> None:
        self._errors = int(res.get("errors", 0) or 0)
        self._meta_labels["errors"].setText(str(self._errors))
        self._meta_labels["rows"].setText(str(res.get("rows", 0)))
        self._meta_labels["elapsed"].setText(f"{time.time() - self._t0:.1f}s")
        self.progress_bar.setValue(self.progress_bar.maximum())
        if self._result_path and Path(self._result_path).exists():
            self.btn_open.setEnabled(True)

    def _on_error(self, err: str) -> None:
        self._append_log(f"[错误] {err}")

    def _open_path(self) -> None:
        if self._result_path and Path(self._result_path).exists():
            import subprocess
            import sys

            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", self._result_path])
            else:
                subprocess.Popen(["xdg-open", self._result_path])
        else:
            QMessageBox.information(self, "打开", "文件不存在或尚未生成。")
