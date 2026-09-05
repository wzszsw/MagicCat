"""功能领域「对象」页通用浏览视图（对标 Navicat 各领域对象页的首列/网格）。

- 顶部操作行：领域专属（如“表”：新建表/打开/删除表；“查询”：新建查询/删除查询）。
- 主体：当前连接+库下的对象表格，列由领域提供。
- 打开某条：双击或“打开” → open_object(profile_id, name)。

本页仅为通用骨架，具体领域（表/视图/函数/查询/备份…）由子类补充列与操作。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ObjectBrowseView(QWidget):
    """领域「对象」页通用骨架。"""

    open_object = Signal(str, str)  # profile_id, name
    new_object = Signal()
    delete_object = Signal(str, str)  # profile_id, name
    refresh_requested = Signal()
    selection_object = Signal(object)  # 选中行对象描述 dict（供信息面板联动）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns: list[str] = []
        self._rows: list[dict] = []
        self._profile_id: str | None = None
        self._context_available = False
        self._tool_buttons: list[QPushButton] = []
        self._icon_kind: str | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._bar = bar
        self.btn_new = QPushButton("新建")
        self.btn_new.clicked.connect(self.new_object.emit)
        self.btn_open = QPushButton("打开")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._emit_open)
        self.btn_del = QPushButton("删除")
        self.btn_del.setEnabled(False)
        self.btn_del.clicked.connect(self._emit_delete)
        bar.addWidget(self.btn_new)
        bar.addWidget(self.btn_open)
        bar.addWidget(self.btn_del)
        bar.addStretch(1)
        self.ctx_label = QLabel("")
        self.ctx_label.setStyleSheet("color: #777;")
        bar.addWidget(self.ctx_label)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        bar.addWidget(self.btn_refresh)
        lay.addLayout(bar)
        self.set_context_available(False)

        self.table = QTableWidget(0, 0)
        self.table.setObjectName("objectBrowseTable")
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setFrameShadow(QFrame.Plain)
        self.table.setLineWidth(0)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setStyleSheet(
            "QTableWidget { border: none; gridline-color: transparent; }"
            "QTableWidget::item { border: none; padding: 3px 8px; }"
            "QTableWidget::item:selected { background-color: #cfe8ff; color: #1f2937; }"
            "QHeaderView { border: none; }"
            "QHeaderView::section { border: none; border-right: 1px solid #d7dee7; "
            "border-bottom: 1px solid #d7dee7; padding: 4px 8px; }"
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        vertical_header = self.table.verticalHeader()
        vertical_header.setVisible(False)
        vertical_header.setDefaultSectionSize(24)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.doubleClicked.connect(self._emit_open)
        self.table.itemSelectionChanged.connect(self._on_selection)
        lay.addWidget(self.table, 1)

    # ---- 子类/领域配置 ----
    def configure(self, columns: list[str], name_column: int = 0,
                  new_text: str = "新建", open_text: str = "打开",
                  delete_text: str = "删除", keys: list[str] | None = None,
                  show_new: bool = True, icon_kind: str | None = None) -> None:
        """由领域页设置：列标题、名称列下标、操作按钮文案、行键名。

        keys：每列对应的数据字典键（缺省与 columns 同值，即直接用列标题取键）。
        show_new：是否显示“新建”按钮（如触发器由表内创建，无需新建入口）。
        """
        self._name_column = name_column
        self._columns = list(columns)
        self._keys = list(keys) if keys is not None else list(columns)
        self._icon_kind = icon_kind
        self.btn_new.setText(new_text)
        self.btn_new.setVisible(show_new)
        self.btn_open.setText(open_text)
        self.btn_del.setText(delete_text)
        self.table.clear()
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        from PySide6.QtWidgets import QHeaderView

        header = self.table.horizontalHeader()
        for c in range(len(columns)):
            mode = (QHeaderView.Interactive if c == name_column
                    else QHeaderView.ResizeToContents)
            header.setSectionResizeMode(c, mode)
        if columns:
            # 名称列保留可拖拽能力，但不再默认吞掉整个中央工作区。
            header.resizeSection(name_column, 320)
            header.setStretchLastSection(True)

    def add_tool_button(self, text: str, handler) -> QPushButton:
        """在操作行（“删除”与伸缩弹簧之间）追加一个领域专属按钮。"""
        btn = QPushButton(text)
        btn.clicked.connect(handler)
        self._bar.insertWidget(self._bar.count() - 1, btn)
        btn.setEnabled(self._context_available)
        self._tool_buttons.append(btn)
        return btn

    def set_context_available(self, available: bool) -> None:
        """设置对象页是否已有可操作的连接/库上下文。"""
        self._context_available = bool(available)
        for button in (self.btn_new, self.btn_refresh, *self._tool_buttons):
            button.setEnabled(self._context_available)
        if not self._context_available:
            self.btn_open.setEnabled(False)
            self.btn_del.setEnabled(False)
        else:
            self._on_selection()

    # ---- 数据填充 ----
    def load(self, profile_id: str, rows: list[dict]) -> None:
        from magiccat.utils.datetime_format import format_datetime

        self.set_context_available(True)
        self._profile_id = profile_id
        self._rows = rows
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(self._keys):
                val = row.get(key, "") or ""
                item = QTableWidgetItem(format_datetime(str(val)))
                if c == self._name_column and self._icon_kind:
                    from magiccat.ui.icons import icon

                    subtype = (str(row.get("type", ""))
                               if self._icon_kind == "routine" else "")
                    item.setIcon(icon(self._icon_kind, subtype))
                self.table.setItem(r, c, item)
        self.table.clearSelection()
        self._on_selection()

    def clear(self) -> None:
        self._profile_id = None
        self._rows = []
        self.table.setRowCount(0)
        self.set_context_available(False)
        self._on_selection()

    # ---- 内部 ----
    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def selected_name(self) -> str:
        row = self._selected_row()
        if row < 0:
            return ""
        item = self.table.item(row, self._name_column)
        return item.text() if item else ""

    def _on_selection(self) -> None:
        has = self._context_available and self._selected_row() >= 0
        self.btn_open.setEnabled(has)
        self.btn_del.setEnabled(has)
        if has:
            desc = self._selection_desc()
            if desc:
                self.selection_object.emit(desc)

    def _selection_desc(self) -> dict | None:
        """选中行 → 对象描述 dict（供信息面板）。子类按领域覆盖。"""
        if self._profile_id is None:
            return None
        name = self.selected_name()
        if not name:
            return None
        return {"kind": "object", "profile_id": self._profile_id, "name": name}

    def _emit_open(self) -> None:
        if self._profile_id is None:
            return
        name = self.selected_name()
        if name:
            self.open_object.emit(self._profile_id, name)

    def _emit_delete(self) -> None:
        if self._profile_id is None:
            return
        name = self.selected_name()
        if name:
            self.delete_object.emit(self._profile_id, name)
