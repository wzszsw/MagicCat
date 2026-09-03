"""表数据页（M4）：分页网格 + 单元格编辑 + 主键定位保存/删除 + 新增行。

编辑模型：
- 加载的行保留“原始值”快照（含主键），单元格改动记录到 dirty 图；
- 点“保存更改”时按行聚合改动 → 主键定位 UPDATE；
- 工具栏“新增行”追加的空行在保存时走 INSERT。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from magiccat.models.profile import ConnectionProfile
from magiccat.services.data_service import DataService
from magiccat.services.metadata_service import MetadataService
from magiccat.ui.grid import DISPLAY_LIMIT, ResultView, _display_text
from magiccat.ui.job import run_async

logger = logging.getLogger(__name__)

PAGE_SIZE = 100


class EditableTableModel(QAbstractTableModel):
    def __init__(self, columns: list[str], rows: list[list], pk_cols: list[str],
                 pk_indexes: list[int]) -> None:
        super().__init__()
        self._columns = columns
        self._rows = rows
        self.pk_cols = pk_cols
        self.pk_indexes = pk_indexes
        self.loaded_count = len(rows)   # 超出此下标的行为“新增行”
        self.dirty: dict[int, dict[int, str]] = {}
        self.readonly = not pk_cols

    # ---- Qt 模型 ----
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        value = self._rows[r][c]
        if role == Qt.DisplayRole:
            return _display_text(value)
        if role == Qt.ToolTipRole and isinstance(value, str) and len(value) > DISPLAY_LIMIT:
            return value
        if role == Qt.ForegroundRole:
            if value is None:
                return QColor("#909090")
            if (r, c) in ((k, v) for k, vv in self.dirty.items() for v in vv):
                return QColor("#B8860B")
            if r >= self.loaded_count:
                return QColor("#2E7D32")
        if role == Qt.BackgroundRole and (r, c) in (
                (k, v) for k, vv in self.dirty.items() for v in vv):
            return QColor("#FFF8DC")
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or role != Qt.EditRole or self.readonly:
            return False
        r, c = index.row(), index.column()
        text = "" if value is None else str(value)
        current = self._rows[r][c]
        if (current is None and text == "") or (current is not None and str(current) == text):
            self.dirty.get(r, {}).pop(c, None)
            if not self.dirty.get(r):
                self.dirty.pop(r, None)
        else:
            self.dirty.setdefault(r, {})[c] = text
            self._rows[r][c] = text if text != "" else None  # 编辑显示原样
        self.dataChanged.emit(index, index)
        return True

    def flags(self, index: QModelIndex):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if not self.readonly:
            base |= Qt.ItemIsEditable
        return base

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._columns):
            name = self._columns[section]
            return ("🔑 " if section in self.pk_indexes else "") + name
        return section + 1

    # ---- 编辑辅助 ----
    def append_new_row(self) -> None:
        """追加一条新增行（None 占位，编辑时回填）。"""
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append([None] * len(self._columns))
        self.endInsertRows()

    def remove_new_row(self, row: int) -> None:
        if row >= self.loaded_count:
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._rows[row]
            self.endRemoveRows()
            if row in self.dirty:
                del self.dirty[row]

    def pk_values_of(self, row: int) -> list:
        """读取原始主键值（来自加载快照；主键被编辑时仍用旧值定位）。"""
        return [self._rows[row][i] for i in self.pk_indexes]

    def edits_of(self, row: int) -> dict[int, str]:
        return dict(self.dirty.get(row, {}))


class DataTableWidget(QWidget):
    """单表数据页。tab_key 供去重。"""

    def __init__(self, profile: ConnectionProfile, schema: str, table: str,
                 data: DataService, metadata: MetadataService, parent=None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.schema = schema
        self.table = table
        self.tab_key = f"{schema}.{table}"
        self._data = data
        self._metadata = metadata
        self._offset = 0
        self._limit = PAGE_SIZE
        self._total = 0
        self._where = ""
        self._sort = None  # (col_name, "ASC"|"DESC")
        self._busy = False
        self._columns_meta: list[dict] = []
        self._pk: list[str] = []
        self._model: EditableTableModel | None = None
        self._errors: list[str] = []

        self._build_ui()
        self._reload()

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_first = QPushButton("⏮")
        self.btn_prev = QPushButton("◀ 上一页")
        self.btn_next = QPushButton("下一页 ▶")
        self.page_label = QLabel("…")
        self.btn_refresh = QPushButton("刷新")
        self.btn_add = QPushButton("新增行")
        self.btn_delete = QPushButton("删除选中")
        self.btn_save = QPushButton("保存更改")
        self.btn_paste = QPushButton("粘贴…")
        self.btn_export = QPushButton("导出…")
        for b in (self.btn_first, self.btn_prev, self.btn_next, self.btn_refresh,
                  self.btn_add, self.btn_delete, self.btn_save, self.btn_paste,
                  self.btn_export):
            bar.addWidget(b)
        self.btn_first.clicked.connect(lambda: self._goto(0))
        self.btn_prev.clicked.connect(lambda: self._goto(max(0, self._offset - self._limit)))
        self.btn_next.clicked.connect(
            lambda: self._goto(self._offset + self._limit))
        self.btn_refresh.clicked.connect(self._reload)
        self.btn_add.clicked.connect(self._add_row)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_save.clicked.connect(self._save_all)
        self.btn_paste.clicked.connect(self._paste_from_clipboard)
        self.btn_export.clicked.connect(self._export_current)
        bar.addStretch(1)
        bar.addWidget(QLabel("筛选:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("WHERE 片段，如 id>10 AND name LIKE '%a%'")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.returnPressed.connect(self._apply_filter)
        bar.addWidget(self.filter_edit, 1)
        root.addLayout(bar)

        self.view = ResultView()
        self.view.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.view._mc_paste_tsv = self._paste_from_clipboard
        root.addWidget(self.view, 1)

        self.status_label = QLabel("")
        root.addWidget(self.status_label)

    # ---- 数据加载 ----
    @staticmethod
    def _order_for(pk: list[str], sort: tuple | None) -> str:
        if sort:
            col, direction = sort
            return f"`{col.replace('`', '``')}` {direction}"
        # 无用户排序时默认按主键升序，保证翻页稳定（无主键则交给数据库默认序）
        if pk:
            return f"`{pk[0].replace('`', '``')}` ASC"
        return ""

    def _reload(self) -> None:
        """后台拉取 列元数据(首次) + 当前页 + 总行数。"""
        if self._busy:
            return
        self._busy = True
        self._set_buttons_enabled(False)
        profile, schema, table = self.profile, self.schema, self.table

        def fetch() -> tuple[list[dict], list[str], dict]:
            cols_meta = self._columns_meta or self._metadata.columns(profile, schema, table)
            pk = self._data.primary_key(profile, schema, table)
            page = self._data.load_page(profile, schema, table,
                                        offset=self._offset, limit=self._limit,
                                        order_by=self._order_for(pk, self._sort) or None,
                                        where=self._where or None)
            return cols_meta, pk, page

        def done(payload) -> None:
            self._busy = False
            self._set_buttons_enabled(True)
            cols_meta, pk, page = payload
            self._columns_meta = cols_meta or self._columns_meta
            self._pk = pk
            self._total = int(page.get("total", 0))
            self._apply_page(page)

        def error(msg: str) -> None:
            self._busy = False
            self._set_buttons_enabled(True)
            self.status_label.setText(f"加载失败：{msg}")
            logger.error("数据页加载失败: %s", msg)

        run_async(fetch, done, error)

    def _apply_page(self, page: dict) -> None:
        columns = page["columns"]
        rows = page["rows"]
        pk_indexes = [columns.index(name) for name in page.get("pk", []) if name in columns]
        self._model = EditableTableModel(columns, rows, list(page.get("pk", [])), pk_indexes)
        self._model.readonly = not self._pk
        self.view.setModel(self._model)
        if not self._pk:
            self.status_label.setText("（该表无主键：只读浏览，编辑/删除已禁用）")
        self._update_page_label()
        if page.get("truncated"):
            self.status_label.setText(
                self.status_label.text() + f" · 仅显示前 {self._limit} 行（请用筛选缩小范围）")

    def _update_page_label(self) -> None:
        if self._total <= 0:
            self.page_label.setText("0 行")
            return
        page_no = self._offset // self._limit + 1
        pages = (self._total - 1) // self._limit + 1
        self.page_label.setText(
            f"第 {page_no}/{pages} 页 · 共 {self._total} 行（当前页 {self._offset + 1}-"
            f"{min(self._offset + self._limit, self._total)}）")
        self.btn_first.setEnabled(self._offset > 0)
        self.btn_prev.setEnabled(self._offset > 0)
        self.btn_next.setEnabled(self._offset + self._limit < self._total)

    def _goto(self, offset: int) -> None:
        if offset < 0 or (self._total and offset >= self._total):
            return
        self._offset = offset
        self._reload()

    def _apply_filter(self) -> None:
        self._where = self.filter_edit.text().strip()
        if ";" in self._where:
            QMessageBox.warning(self, "筛选", "筛选片段不能包含分号。")
            self._where = ""
            self.filter_edit.clear()
            return
        self._offset = 0
        self._reload()

    def _on_header_clicked(self, logical_index: int) -> None:
        if self._model is None:
            return
        col_name = self._model._columns[logical_index]
        if self._sort and self._sort[0] == col_name:
            direction = "DESC" if self._sort[1] == "ASC" else "ASC"
        else:
            direction = "ASC"
        self._sort = (col_name, direction)
        self._offset = 0
        self._reload()

    # ---- 编辑动作 ----
    def _add_row(self) -> None:
        if not self._pk:
            return
        if self._model is None:
            return
        self._model.append_new_row()
        self.status_label.setText("已新增一行：填写内容后点「保存更改」")

    def _delete_selected(self) -> None:
        if self._model is None or not self._pk:
            return
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()},
                      reverse=True)
        loaded = [r for r in rows if r < self._model.loaded_count]
        if not loaded:
            for r in rows:
                self._model.remove_new_row(r)
            self.status_label.setText("已移除未保存的新增行")
            return
        if QMessageBox.question(self, "删除行", f"确定删除选中的 {len(loaded)} 行？"
                                ) != QMessageBox.Yes:
            return
        self._busy = True
        self._set_buttons_enabled(False)
        profile, schema, table = self.profile, self.schema, self.table
        pk = self._pk

        def fetch() -> list[str]:
            errs: list[str] = []
            for r in sorted(loaded):
                try:
                    self._data.delete_row(profile, schema, table,
                                          pk, self._model.pk_values_of(r))
                except Exception as exc:  # noqa: BLE001
                    errs.append(f"行 {r + 1}: {exc}")
            return errs

        def done(errs: list[str]) -> None:
            self._busy = False
            self._set_buttons_enabled(True)
            self._errors = errs
            self._offset = min(self._offset, max(0, self._total - len(loaded) - 1))
            self._reload()
            if errs:
                self.status_label.setText(f"删除部分失败：{len(errs)} 行")

        run_async(fetch, done, lambda m: self._set_buttons_enabled(True))

    def _save_all(self) -> None:
        if self._model is None:
            return
        if not self._pk and any(r >= self._model.loaded_count for r in range(self._model.rowCount())):
            self.status_label.setText("无主键表不支持新增行")
            return
        profile, schema, table = self.profile, self.schema, self.table
        pk = self._pk
        columns = self._model._columns
        nullable = {c["name"]: (c.get("nullable", "NO") == "YES")
                    for c in self._columns_meta}
        self._busy = True
        self._set_buttons_enabled(False)

        def collect() -> tuple[list[tuple], list[tuple]]:
            """返回 (updates[(row, ...)], inserts[(cols, vals)])。"""
            updates: list[tuple] = []
            inserts: list[tuple] = []
            for r in range(self._model.rowCount()):
                edits = self._model.edits_of(r)
                if not edits:
                    continue
                if r >= self._model.loaded_count:  # 新增行 → INSERT
                    cols, vals = [], []
                    for c in sorted(edits):
                        col = columns[c]
                        raw = edits[c]
                        vals.append(None if (raw == "" and nullable.get(col, False)) else raw)
                        cols.append(col)
                    if cols:
                        inserts.append((cols, vals))
                else:  # 已有行 → 按主键 UPDATE
                    set_cols = [columns[c] for c in sorted(edits)]
                    set_vals = [None if (edits[c] == "" and nullable.get(columns[c], False))
                                else edits[c] for c in sorted(edits)]
                    updates.append((r, set_cols, set_vals))
            return updates, inserts

        def fetch(payload) -> list[str]:
            updates, inserts = payload
            errs: list[str] = []
            for r, set_cols, set_vals in updates:
                try:
                    self._data.update_row(profile, schema, table, pk,
                                          self._model.pk_values_of(r),
                                          set_cols, set_vals)
                except Exception as exc:  # noqa: BLE001
                    errs.append(f"行 {r + 1}: {exc}")
            for cols, vals in inserts:
                try:
                    self._data.insert_row(profile, schema, table, cols, vals)
                except Exception as exc:  # noqa: BLE001
                    errs.append(f"新增行: {exc}")
            return errs

        def done(errs: list[str]) -> None:
            self._busy = False
            self._set_buttons_enabled(True)
            if errs:
                QMessageBox.warning(self, "保存更改", "\n".join(errs))
            self._errors = errs
            self._reload()

        def error(msg: str) -> None:
            self._busy = False
            self._set_buttons_enabled(True)
            self.status_label.setText(f"保存失败：{msg}")

        run_async(lambda: fetch(collect()), done, error)

    def _paste_from_clipboard(self) -> None:
        """从剪贴板粘贴 TSV（Excel 复制）到当前单元格区域，改动标记为待保存。"""
        from PySide6.QtGui import QGuiApplication

        if self._model is None or self._model.readonly:
            self.status_label.setText("该表只读或无主键，不支持粘贴。")
            return
        text = QGuiApplication.clipboard().text()
        if not text:
            self.status_label.setText("剪贴板为空。")
            return
        lines = [line for line in text.replace("\r\n", "\n").split("\n") if line != ""]
        if not lines:
            return
        model = self._model
        # 起点：当前选中区左上角，否则 (0,0)
        start_row = self._model.rowCount()
        start_col = 0
        current = self.view.currentIndex()
        if current.isValid():
            start_row, start_col = current.row(), current.column()
        count = 0
        for i, line in enumerate(lines):
            row = start_row + i
            if row >= model.rowCount():
                break
            for j, token in enumerate(line.split("\t")):
                col = start_col + j
                if col >= model.columnCount():
                    break
                model.setData(model.index(row, col, QModelIndex()), token)
                count += 1
        self.status_label.setText(f"已粘贴 {len(lines)} 行 · {count} 个单元格（点「保存更改」提交）")

    def _export_current(self) -> None:
        from magiccat.ui.transfer_dialogs import run_export

        run_export(self, self.profile, self.schema, self.table,
                   self._data, self._metadata, where=self._where or None)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for b in (self.btn_first, self.btn_prev, self.btn_next, self.btn_refresh,
                  self.btn_add, self.btn_delete, self.btn_save, self.btn_paste,
                  self.btn_export):
            b.setEnabled(enabled)
