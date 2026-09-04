"""查询编辑器标签页的完整工作区（对标 Navicat 每查询页一套）。

每个查询标签页独立持有：
- 头部条：连接下拉 + 库下拉 + 保存/运行/停止/解释 + 美化 SQL/代码段/询问 AI；
- 编辑器（monaco 或自研）；
- 每标签结果面板（多结果集 / 消息）；
- 底部状态行。

连接/库选择**只作用于本标签**（影响不扩散）。MainWindow 经信号接入执行/结果。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from magiccat.ui.result_panel import ResultPanel


class QueryWorkspace(QWidget):
    """单个查询标签页的工作区（连接/库/编辑器/结果/状态）。"""

    run_requested = Signal()
    run_all_requested = Signal()
    stop_requested = Signal()
    explain_requested = Signal()
    save_requested = Signal()
    format_requested = Signal()
    snippet_requested = Signal()
    ask_ai_requested = Signal()

    def __init__(self, editor, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        bar.addWidget(QLabel(" 连接: "))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(170)
        bar.addWidget(self.profile_combo)
        bar.addWidget(QLabel(" 库: "))
        self.schema_combo = QComboBox()
        self.schema_combo.setMinimumWidth(150)
        bar.addWidget(self.schema_combo)
        bar.addSpacing(10)
        self.btn_save = self._btn("保存查询", self.save_requested, bar)
        self.btn_run = self._btn("运行", self.run_requested, bar)
        self.btn_run_all = self._btn("执行全部", self.run_all_requested, bar)
        self.btn_stop = self._btn("停止", self.stop_requested, bar)
        self.btn_stop.setEnabled(False)
        self.btn_explain = self._btn("解释", self.explain_requested, bar)
        self.btn_format = self._btn("美化 SQL", self.format_requested, bar)
        self.btn_snippet = self._btn("代码段", self.snippet_requested, bar)
        self.btn_ask_ai = self._btn("询问 AI", self.ask_ai_requested, bar)
        bar.addStretch(1)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(editor)
        self.result_panel = ResultPanel()
        self.result_panel.setVisible(False)
        splitter.addWidget(self.result_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        self.status_label = QLabel("")
        root.addWidget(self.status_label)

        self._edit_actions = (self.btn_run, self.btn_run_all, self.btn_stop,
                              self.btn_save, self.btn_explain, self.btn_format,
                              self.btn_snippet, self.btn_ask_ai)

    @staticmethod
    def _btn(text: str, signal: Signal, bar: QHBoxLayout) -> QPushButton:
        btn = QPushButton(text)
        btn.clicked.connect(signal.emit)
        bar.addWidget(btn)
        return btn

    # ---- 连接/库/状态 ----
    def set_profile(self, profile_id: str) -> None:
        idx = self.profile_combo.findData(profile_id)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)

    def set_schema(self, schema: str) -> None:
        i = self.schema_combo.findText(schema)
        if i >= 0:
            self.schema_combo.setCurrentIndex(i)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_busy(self, busy: bool) -> None:
        self.btn_run.setEnabled(not busy)
        self.btn_run_all.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)

    # ---- 委托编辑器接口（兼容：上层/测试对返回对象直接调用编辑器方法） ----
    def setPlainText(self, text: str) -> None:
        self.editor.setPlainText(text)

    def toPlainText(self) -> str:
        return self.editor.toPlainText()

    def text(self) -> str:
        return self.editor.text()

    def all_text(self) -> str:
        return self.editor.all_text()

    def current_sql(self) -> str | None:
        return self.editor.current_sql()

    def statements(self) -> list[str]:
        return self.editor.statements()

    def set_completion_words(self, words: list[str]) -> None:
        if hasattr(self.editor, "set_completion_words"):
            self.editor.set_completion_words(words)

    def set_completion_data(self, data: dict) -> None:
        if hasattr(self.editor, "set_completion_data"):
            self.editor.set_completion_data(data)

    def setFocus(self) -> None:
        self.editor.setFocus()
