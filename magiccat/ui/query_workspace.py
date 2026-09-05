"""查询编辑器标签页的完整工作区（对标 Navicat 每查询页一套）。

每个查询标签页独立持有：
- 头部条：连接下拉 + Catalog/Schema 下拉 + 保存/运行/停止/解释 + 美化 SQL/代码段/询问 AI；
- 编辑器（monaco 或自研）；
- 每标签结果面板（多结果集 / 消息）；
- 底部状态行。

连接/Catalog/Schema 选择**只作用于本标签**（影响不扩散）。MainWindow 经信号接入执行/结果。
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
    """单个查询标签页的工作区（连接/Catalog/Schema/编辑器/结果/状态）。"""

    run_requested = Signal()
    stop_requested = Signal()
    explain_requested = Signal()
    save_requested = Signal()
    format_requested = Signal()
    snippet_requested = Signal()
    ask_ai_requested = Signal()

    def __init__(self, editor, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        # 对象树新建查询时列表可能仍在异步加载，先暂存目标上下文。
        self._pending_database = ""
        # None 表示没有指定目标；空字符串表示库级
        # 右键新建查询明确要求模式保持空白。
        self._pending_schema: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("连接")
        self.profile_combo.setMinimumWidth(170)
        bar.addWidget(self.profile_combo)
        # JDBC 的 catalog 在 MySQL 中就是 database，在 PG/GaussDB 中是连接目标库。
        self.database_combo = QComboBox()
        self.database_combo.setObjectName("database_combo")
        self.database_combo.setToolTip("Catalog / 数据库")
        self.database_combo.setMinimumWidth(150)
        bar.addWidget(self.database_combo)
        # 保留 catalog_combo 命名，便于调用方按 JDBC 术语访问；两者指向同一控件。
        self.catalog_combo = self.database_combo
        self.schema_combo = QComboBox()
        self.schema_combo.setObjectName("schema_combo")
        self.schema_combo.setToolTip("Schema / 模式")
        self.schema_combo.setMinimumWidth(140)
        self.schema_combo.setEnabled(False)
        bar.addWidget(self.schema_combo)
        bar.addSpacing(10)
        self.btn_save = self._btn("保存查询", self.save_requested, bar)
        self.btn_run = self._btn("运行", self.run_requested, bar)
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

        self._edit_actions = (self.btn_run, self.btn_stop,
                              self.btn_save, self.btn_explain, self.btn_format,
                              self.btn_snippet, self.btn_ask_ai)

        # 运行按钮文案跟随当前编辑器是否有选区；两种编辑器均提供兼容信号。
        selection_changed = getattr(editor, "selectionChanged", None)
        if selection_changed is not None and hasattr(selection_changed, "connect"):
            selection_changed.connect(self._update_run_label)
        self._update_run_label()

    @staticmethod
    def _btn(text: str, signal: Signal, bar: QHBoxLayout) -> QPushButton:
        btn = QPushButton(text)
        btn.clicked.connect(signal.emit)
        bar.addWidget(btn)
        return btn

    # ---- 连接/Catalog/Schema/状态 ----
    def set_profile(self, profile_id: str) -> None:
        idx = self.profile_combo.findData(profile_id)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)

    def set_database(self, database: str) -> None:
        value = (database or "").strip()
        self._pending_database = value
        i = self.database_combo.findText(value)
        if i >= 0:
            self.database_combo.setCurrentIndex(i)
            self._pending_database = ""

    def set_catalog(self, catalog: str) -> None:
        """按 JDBC 术语设置 Catalog（与 set_database 等价）。"""
        self.set_database(catalog)

    def set_schema(self, schema: str) -> None:
        value = (schema or "").strip()
        self._pending_schema = value
        i = self.schema_combo.findText(value)
        if i >= 0:
            self.schema_combo.setCurrentIndex(i)
        elif not value and self.schema_combo.count():
            # 数据库级右键目标明确没有 Schema；即使列表已提前加载，也要清空当前选项。
            self.schema_combo.setCurrentIndex(-1)
            self._pending_schema = ""

    def set_schema_visible(self, visible: bool) -> None:
        """按数据库方言显示模式选择。

        MySQL/MariaDB 没有独立 JDBC schema，因此模式控件一起隐藏，
        不在查询工具栏留下空白或可误操作的入口。
        """
        self.schema_combo.setVisible(visible)
        if not visible:
            self.schema_combo.blockSignals(True)
            self.schema_combo.clear()
            self.schema_combo.setEnabled(False)
            self.schema_combo.blockSignals(False)

    def clear_pending_context(self) -> None:
        """丢弃上一个连接留下的异步上下文定位。"""
        self._pending_database = ""
        self._pending_schema = None

    def selected_database(self) -> str:
        return (self.database_combo.currentText() or "").strip()

    def selected_catalog(self) -> str:
        """返回当前 JDBC Catalog。"""
        return self.selected_database()

    def selected_schema(self) -> str | None:
        """返回当前 JDBC Schema；MySQL 等禁用时明确返回 None。"""
        if not self.schema_combo.isEnabled():
            return None
        value = (self.schema_combo.currentText() or "").strip()
        return value or None

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_busy(self, busy: bool) -> None:
        self.btn_run.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)

    def _update_run_label(self, selected: bool | None = None) -> None:
        has_selection = bool(selected) if selected is not None else False
        if selected is not None:
            self.btn_run.setText("运行已选择的" if has_selection else "运行")
            return
        checker = getattr(self.editor, "has_selection", None)
        if callable(checker):
            has_selection = bool(checker())
        else:
            cursor = getattr(self.editor, "textCursor", lambda: None)()
            has_selection = bool(cursor is not None and cursor.hasSelection())
        self.btn_run.setText("运行已选择的" if has_selection else "运行")

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

    def selected_text(self) -> str | None:
        return self.editor.selected_text()

    def sql_for_run(self) -> str:
        """无选区运行全文；有选区时仅运行选中的 SQL。"""
        selected = self.selected_text()
        return selected if selected is not None else self.all_text()

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
