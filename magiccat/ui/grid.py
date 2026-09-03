"""结果网格：QTableView + 只读模型（超长文本显示截断，复制/导出保留全文）。

- NULL 单元格灰显 “NULL”
- DisplayRole：超过 DISPLAY_LIMIT 字符的单元格截断显示；
  ToolTipRole 与 复制/导出（走原始行）仍取完整值。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableView

DISPLAY_LIMIT = 1200


def _display_text(value) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    if len(text) > DISPLAY_LIMIT:
        return text[:DISPLAY_LIMIT - 1] + "…"
    return text


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
            return _display_text(value)
        if role == Qt.ToolTipRole and isinstance(value, str) and len(value) > DISPLAY_LIMIT:
            return value
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

    # ---- 导出当前结果到 CSV ----
    def export_csv(self, path: str | Path) -> int:
        """把当前页结果写为 CSV（utf-8-sig；NULL→空串）。返回写入行数。"""
        import csv

        model = self.model()
        if model is None:
            return 0
        rows: list[list] | None = getattr(model, "_rows", None)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            headers = [model.headerData(c, Qt.Horizontal) or "" for c in range(model.columnCount())]
            writer.writerow(headers)
            count = 0
            for r in range(model.rowCount()):
                if rows is not None and 0 <= r < len(rows) and len(rows[r]) == len(headers):
                    line = ["" if v is None else v for v in rows[r]]
                else:
                    line = [model.index(r, c).data(Qt.DisplayRole) or "" for c in range(len(headers))]
                writer.writerow(line)
                count += 1
        return count

    # ---- 复制（右键菜单） ----
    def _show_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        act_tsv = menu.addAction("复制(TSV)")
        act_tsv_header = menu.addAction("复制带表头(TSV)")
        act_export = menu.addAction("导出当前结果到 CSV…")
        paste_fn = getattr(self, "_mc_paste_tsv", None)
        if paste_fn is not None:
            act_paste = menu.addAction("粘贴(TSV)…")
        else:
            act_paste = None
        menu.addSeparator()
        act_select_all = menu.addAction("全选")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_tsv:
            self.copy_selection(include_header=False)
        elif chosen is act_tsv_header:
            self.copy_selection(include_header=True)
        elif chosen is act_export:
            self._export_csv_dialog()
        elif chosen is act_paste:
            paste_fn()
        elif chosen is act_select_all:
            self.selectAll()

    def _export_csv_dialog(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        path, _f = QFileDialog.getSaveFileName(self, "导出当前结果", "result.csv",
                                               "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            rows = self.export_csv(path)
        except OSError as exc:
            QMessageBox.critical(self, "导出", f"写入失败：{exc}")
            return
        QMessageBox.information(self, "导出", f"已导出 {rows} 行 →\n{path}")

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
        raw_rows: list[list] | None = getattr(model, "_rows", None)
        if include_header:
            lines.append([model.headerData(c, Qt.Horizontal) or "" for c in cols])
        for r in rows:
            if raw_rows is not None and 0 <= r < len(raw_rows) and len(raw_rows[r]) == len(cols):
                # 原始行：NULL→"NULL"（与既有显示语义一致），超长文本保持完整
                lines.append(["NULL" if v is None else str(v) for v in raw_rows[r]])
            else:
                lines.append([model.index(r, c).data(Qt.DisplayRole) or "" for c in cols])
        text = "\n".join("\t".join(str(v) for v in line) for line in lines)
        QGuiApplication.clipboard().setText(text)
        return text
