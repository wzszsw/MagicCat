"""表设计器（M4b）：可视化列编辑（可增删改）+ 索引/外键浏览 + ALTER/CREATE 预览与执行。

约束：主键/索引/外键的结构变更请使用 SQL 编辑器完成；本设计器负责列结构，
并在 SQL 预览页给出服务器当前 DDL 与计算出的变更语句。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.ddl_builder import (
    alter_fragments,
    group_foreign_keys,
    group_indexes,
)
from magiccat.services.ddl_service import DdlService
from magiccat.services.query_service import QueryService
from magiccat.ui.job import run_async

logger = logging.getLogger(__name__)

_COL_HEADERS = ["列名", "类型", "可空(NO/YES)", "默认值", "注释"]


class TableDesignerDialog(QDialog):
    def __init__(self, profile: ConnectionProfile, schema: str, table: str,
                 connections: ConnectionService, parent=None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.schema = schema
        self.table = table
        self._connections = connections
        self._ddl = DdlService(connections)
        self._query = QueryService(connections)
        self._snapshot: dict = {}
        self._orig_columns: list[dict] = []
        self.setWindowTitle(f"设计表 · {schema}.{table}（{profile.name}）")
        self.resize(860, 620)
        self._build_ui()
        self._load()

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.status_label = QLabel("加载中…")
        root.addWidget(self.status_label)

        self.tabs = QTabWidget()

        # 列
        self.columns_grid = QTableWidget(0, len(_COL_HEADERS))
        self.columns_grid.setHorizontalHeaderLabels(_COL_HEADERS)
        self.columns_grid.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.columns_grid, "列")

        # 索引 / 外键（只读）
        self.indexes_grid = QTableWidget(0, 3)
        self.indexes_grid.setHorizontalHeaderLabels(["索引", "类型", "列"])
        self.indexes_grid.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabs.addTab(self.indexes_grid, "索引")

        self.fk_grid = QTableWidget(0, 4)
        self.fk_grid.setHorizontalHeaderLabels(["约束", "列", "引用", "规则"])
        self.fk_grid.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabs.addTab(self.fk_grid, "外键")

        # SQL 预览
        self.sql_preview = QPlainTextEdit()
        self.sql_preview.setReadOnly(True)
        self.sql_preview.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.sql_preview, "SQL 预览")
        root.addWidget(self.tabs, 1)

        bar = QHBoxLayout()
        btn_add = QPushButton("新增列")
        btn_del = QPushButton("删除选中列")
        btn_refresh = QPushButton("刷新")
        btn_preview = QPushButton("生成 SQL 预览")
        btn_copy = QPushButton("复制 DDL")
        btn_apply = QPushButton("应用变更")
        btn_close = QPushButton("关闭")
        for b in (btn_add, btn_del, btn_refresh, btn_preview, btn_copy, btn_apply, btn_close):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        self.btn_apply = btn_apply
        btn_add.clicked.connect(self._add_column_row)
        btn_del.clicked.connect(self._delete_column_rows)
        btn_refresh.clicked.connect(self._load)
        btn_preview.clicked.connect(self._generate_preview)
        btn_copy.clicked.connect(self._copy_ddl)
        btn_apply.clicked.connect(self._apply)
        btn_close.clicked.connect(self.accept)

    # ---- 加载 ----
    def _load(self) -> None:
        profile, schema, table = self.profile, self.schema, self.table
        self.btn_apply.setEnabled(False)
        self.status_label.setText("加载表结构…")

        def fetch() -> dict:
            return self._ddl.snapshot(profile, schema, table)

        def done(snapshot: dict) -> None:
            self._snapshot = snapshot
            self._orig_columns = list(snapshot["columns"])
            self._fill_columns(snapshot["columns"])
            self._fill_readonly(self.indexes_grid, [
                (g["index_name"],
                 "UNIQUE" if not _falsy(g.get("non_unique")) else "普通",
                 ", ".join(g["columns"]))
                for g in group_indexes(snapshot["indexes"])])
            self._fill_readonly(self.fk_grid, [
                (g["constraint_name"], ", ".join(g["columns"]),
                 f"{g['ref_table']}({', '.join(g['ref_columns'])})",
                 f"DEL {g['on_delete']} · UPD {g['on_update']}")
                for g in group_foreign_keys(snapshot["foreign_keys"])])
            self.sql_preview.setPlainText("# 服务器当前 DDL：\n" + snapshot["create_sql"])
            self.status_label.setText(f"已加载：{len(snapshot['columns'])} 列 · "
                                      f"{len(snapshot['indexes'])} 条索引记录")
            self.btn_apply.setEnabled(True)

        run_async(fetch, done, lambda err: self.status_label.setText(f"加载失败：{err}"))

    def _fill_columns(self, columns: list[dict]) -> None:
        grid = self.columns_grid
        grid.setRowCount(len(columns))
        for r, c in enumerate(columns):
            values = [c["name"], c["data_type"], c.get("nullable", "NO"),
                      c.get("default_value") or "", c.get("comment") or ""]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.UserRole, dict(c))  # 保留 extra/key 等原值
                grid.setItem(r, col, item)

    @staticmethod
    def _fill_readonly(grid: QTableWidget, rows: list[tuple]) -> None:
        grid.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                grid.setItem(r, c, item)

    def _add_column_row(self) -> None:
        r = self.columns_grid.rowCount()
        self.columns_grid.insertRow(r)
        base = {"name": "new_col", "data_type": "varchar(255)", "nullable": "YES",
                "default_value": None, "extra": "", "key": "", "comment": ""}
        for col, text in enumerate(["new_col", "varchar(255)", "YES", "", ""]):
            item = QTableWidgetItem(text)
            if col == 0:
                item.setData(Qt.UserRole, dict(base))
            self.columns_grid.setItem(r, col, item)

    def _delete_column_rows(self) -> None:
        rows = sorted({i.row() for i in self.columns_grid.selectedIndexes()}, reverse=True)
        for r in rows:
            self.columns_grid.removeRow(r)

    # ---- 读编辑结果 ----
    def _read_columns(self) -> list[dict]:
        out: list[dict] = []
        grid = self.columns_grid
        for r in range(grid.rowCount()):
            base = grid.item(r, 0).data(Qt.UserRole) if grid.item(r, 0) else {}
            base = dict(base or {})
            name = (grid.item(r, 0).text() if grid.item(r, 0) else "").strip()
            if not name:
                continue
            base["name"] = name
            base["data_type"] = (grid.item(r, 1).text() if grid.item(r, 1) else "").strip()
            base["nullable"] = (grid.item(r, 2).text() if grid.item(r, 2) else "YES").strip().upper()
            default_item = grid.item(r, 3)
            base["default_value"] = (default_item.text().strip()
                                     if default_item and default_item.text().strip() else None)
            comment_item = grid.item(r, 4)
            base["comment"] = (comment_item.text().strip() if comment_item else "")
            out.append(base)
        return out

    # ---- SQL 生成与执行 ----
    def _build_sql(self, edited: list[dict]) -> str | None:
        frags = alter_fragments(self._orig_columns, edited)
        if not frags:
            return None
        from magiccat.services.ddl_builder import _q

        head = f"ALTER TABLE {_q(self.schema)}.{_q(self.table)} "
        return ";\n".join(head + f for f in frags)

    def _generate_preview(self) -> None:
        edited = self._read_columns()
        sql = self._build_sql(edited)
        if sql is None:
            self.sql_preview.setPlainText(
                "# 服务器当前 DDL：\n" + self._snapshot.get("create_sql", "")
                + "\n\n# 未检测到列变更")
            self.status_label.setText("未检测到列变更")
            return
        self.sql_preview.setPlainText(
            "# 服务器当前 DDL：\n" + self._snapshot.get("create_sql", "")
            + "\n\n# 变更预览（将执行）：\n" + sql + ";")
        self.status_label.setText(f"预览就绪：{len(edited)} 列，{sql.count('COLUMN')} 处变更")

    def _copy_ddl(self) -> None:
        text = self.sql_preview.toPlainText()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.status_label.setText("已复制到剪贴板", 3000)

    def _apply(self) -> None:
        edited = self._read_columns()
        sql = self._build_sql(edited)
        if sql is None:
            QMessageBox.information(self, "应用变更", "未检测到列变更。")
            return
        if QMessageBox.question(self, "应用变更",
                                "将执行以下语句，是否继续？\n\n" + sql + ";"
                                ) != QMessageBox.Yes:
            return
        profile = self.profile
        self.btn_apply.setEnabled(False)
        self.status_label.setText("正在应用变更…")
        run_async(
            lambda: self._query.execute(profile, sql),
            lambda results: self._on_applied(results),
            lambda err: self._after_apply_error(err))

    def _on_applied(self, results: list[dict]) -> None:
        errors = [r for r in results if r.get("kind") == "error"]
        if errors:
            QMessageBox.warning(self, "应用变更", "\n".join(e["message"] for e in errors))
        else:
            QMessageBox.information(self, "应用变更",
                                    f"变更成功（{len(results)} 条语句）。")
        self._load()

    def _after_apply_error(self, err: str) -> None:
        self.btn_apply.setEnabled(True)
        QMessageBox.critical(self, "应用变更", f"执行失败：{err}")
        self.status_label.setText("应用失败")


def _falsy(v) -> bool:
    return v in (0, "0", False, "false", "no", "NO")
