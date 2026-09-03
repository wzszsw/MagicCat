"""查询领域「对象」页（对标 Navicat 查询工作区的“对象”固定标签页）。

- 顶部操作行：新建查询 / 删除查询（“设计查询”=查询构建工具，属高级功能，本轮不做）。
- 主体：当前连接+库下的已存查询表格（名称 / 修改日期 / 库）。
- 打开某条：双击该行 → open_query(profile_id, name)，由主窗口切到编辑态并载入。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from magiccat.services import query_library


class QueryBrowseView(QWidget):
    """查询领域·「对象」浏览页。"""

    open_query = Signal(str, str)  # profile_id, name
    new_query = Signal()
    delete_query = Signal(str, str)  # profile_id, name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.btn_new = QPushButton("新建查询")
        self.btn_new.clicked.connect(self.new_query.emit)
        self.btn_del = QPushButton("删除查询")
        self.btn_del.clicked.connect(self._emit_delete)
        bar.addWidget(self.btn_new)
        bar.addWidget(self.btn_del)
        bar.addStretch(1)
        self.ctx_label = QLabel("")
        self.ctx_label.setStyleSheet("color: #777;")
        bar.addWidget(self.ctx_label)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["名称", "修改日期", "库"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(self._emit_open)
        lay.addWidget(self.table, 1)

        self._profile_id: str | None = None

    # ---- 对外 ----
    def load_queries(self, profile_id: str, schema: str) -> None:
        """拉取该连接下匹配 schema 的具名查询并填充表格。"""
        self._profile_id = profile_id
        items = query_library.QueryLibrary.default().list(profile_id)
        rows = [q for q in items if (q.get("schema") or "") == schema]
        self.table.setRowCount(len(rows))
        for r, q in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(q.get("name", "")))
            self.table.setItem(r, 1, QTableWidgetItem(q.get("updated_at", "")))
            self.table.setItem(r, 2, QTableWidgetItem(q.get("schema", "")))
        self.table.clearSelection()

    def clear(self) -> None:
        self._profile_id = None
        self.table.setRowCount(0)

    def selected_name(self) -> str:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return ""
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item else ""

    # ---- 内部 ----
    def _emit_open(self) -> None:
        if self._profile_id is None:
            return
        name = self.selected_name()
        if name:
            self.open_query.emit(self._profile_id, name)

    def _emit_delete(self) -> None:
        if self._profile_id is None:
            return
        name = self.selected_name()
        if name:
            self.delete_query.emit(self._profile_id, name)
