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
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setDefaultSectionSize(160)
        self.verticalHeader().setDefaultSectionSize(24)
