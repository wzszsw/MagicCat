"""结果网格（M3 起点）：QTableView + 只读模型；分页/编辑在 M4 增强。

- NULL 单元格灰显 “NULL”
- 行数截断提示由 ResultPanel 处理
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableView


class ResultTableModel(QAbstractTableModel):
    def __init__(self, columns: list[str], rows: list[list]) -> None:
        super().__init__()
        self._columns = columns
        self._rows = rows

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008 —— Qt 模型签名要求
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        value = self._rows[index.row()][index.column()]
        if role == Qt.DisplayRole:
            if value is None:
                return "NULL"
            return str(value)
        if role == Qt.ForegroundRole and value is None:
            return QColor("#909090")
        if role == Qt.TextAlignmentRole:
            return Qt.AlignLeft | Qt.AlignVCenter
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._columns):
            return self._columns[section]
        return section + 1


class ResultView(QTableView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setDefaultSectionSize(160)
        self.verticalHeader().setDefaultSectionSize(24)

    # ---- 复制（右键菜单） ----
    def _show_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        act_tsv = menu.addAction("复制(TSV)")
        act_tsv_header = menu.addAction("复制带表头(TSV)")
        menu.addSeparator()
        act_select_all = menu.addAction("全选")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_tsv:
            self.copy_selection(include_header=False)
        elif chosen is act_tsv_header:
            self.copy_selection(include_header=True)
        elif chosen is act_select_all:
            self.selectAll()

    def copy_selection(self, include_header: bool = True) -> str:
        """选中行（无选中则整页）→ TSV → 剪贴板。返回复制的文本（测试可断言）。"""
        from PySide6.QtGui import QGuiApplication

        model = self.model()
        if model is None:
            return ""
        selection = self.selectionModel()
        rows = sorted({i.row() for i in selection.selectedRows()}) if selection else []
        if not rows:
            rows = list(range(model.rowCount()))
        cols = list(range(model.columnCount()))
        lines: list[list] = []
        if include_header:
            lines.append([model.headerData(c, Qt.Horizontal) or "" for c in cols])
        for r in rows:
            # DisplayRole 已把 None 渲染为 "NULL"，其余原样（含空串）
            lines.append([model.index(r, c).data(Qt.DisplayRole) for c in cols])
        text = "\n".join("\t".join(str(v) for v in line) for line in lines)
        QGuiApplication.clipboard().setText(text)
        return text
