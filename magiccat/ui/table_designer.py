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
    QWidget,
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
                 connections: ConnectionService, parent=None,
                 new_table: bool = False) -> None:
        super().__init__(parent)
        self.profile = profile
        self.schema = schema
        self.table = table
        self.new_table = new_table
        self._connections = connections
        self._ddl = DdlService(connections)
        self._query = QueryService(connections)
        self._snapshot: dict = {}
        self._orig_columns: list[dict] = []
        self._orig_indexes: list[dict] = []
        self._indexes: list[dict] = []  # 工作副本（应用时与 _orig_indexes 求差）
        self._orig_fks: list[dict] = []
        self._fks: list[dict] = []  # 外键工作副本
        title = f"新建表 · {schema}.{table}" if new_table else f"设计表 · {schema}.{table}"
        self.setWindowTitle(f"{title}（{profile.name}）")
        self.resize(860, 620)
        self._build_ui()
        if new_table:
            self._init_new()
        else:
            self._load()

    def _init_new(self) -> None:
        """新建表模式：无需元数据快照，直接给出空列行等待填写。"""
        self._snapshot = {"create_sql": ""}
        self.status_label.setText(
            "新建表：逐行填写列定义（列名/类型/可空/默认值/注释），"
            "然后点「生成 SQL 预览」并「应用变更」")
        self.sql_preview.setPlainText("# 填写列后点「生成 SQL 预览」生成 CREATE TABLE")
        self._add_column_row()

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

        # 索引（可管理：新增/删除选中）
        self.indexes_grid = QTableWidget(0, 3)
        self.indexes_grid.setHorizontalHeaderLabels(["索引", "类型", "列"])
        self.indexes_grid.setEditTriggers(QTableWidget.NoEditTriggers)
        idx_tab = QWidget()
        idx_lay = QVBoxLayout(idx_tab)
        idx_lay.setContentsMargins(4, 4, 4, 4)
        idx_bar = QHBoxLayout()
        btn_idx_add = QPushButton("新增索引…")
        btn_idx_del = QPushButton("删除选中索引")
        idx_bar.addWidget(btn_idx_add)
        idx_bar.addWidget(btn_idx_del)
        idx_bar.addStretch(1)
        idx_lay.addLayout(idx_bar)
        idx_lay.addWidget(self.indexes_grid, 1)
        self.btn_idx_add = btn_idx_add
        self.btn_idx_del = btn_idx_del
        btn_idx_add.clicked.connect(self._add_index)
        btn_idx_del.clicked.connect(self._remove_index_selected)
        self.tabs.addTab(idx_tab, "索引")

        self.fk_grid = QTableWidget(0, 4)
        self.fk_grid.setHorizontalHeaderLabels(["约束", "列", "引用", "规则"])
        self.fk_grid.setEditTriggers(QTableWidget.NoEditTriggers)
        fk_tab = QWidget()
        fk_lay = QVBoxLayout(fk_tab)
        fk_lay.setContentsMargins(4, 4, 4, 4)
        fk_bar = QHBoxLayout()
        btn_fk_add = QPushButton("新增外键…")
        btn_fk_del = QPushButton("删除选中外键")
        fk_bar.addWidget(btn_fk_add)
        fk_bar.addWidget(btn_fk_del)
        fk_bar.addStretch(1)
        fk_lay.addLayout(fk_bar)
        fk_lay.addWidget(self.fk_grid, 1)
        self.btn_fk_add = btn_fk_add
        self.btn_fk_del = btn_fk_del
        btn_fk_add.clicked.connect(self._add_fk)
        btn_fk_del.clicked.connect(self._remove_fk_selected)
        self.tabs.addTab(fk_tab, "外键")

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
            self._orig_indexes = group_indexes(snapshot["indexes"])
            self._indexes = [dict(g, columns=list(g["columns"]))
                             for g in self._orig_indexes]
            self._orig_fks = group_foreign_keys(snapshot["foreign_keys"])
            self._fks = [dict(g, columns=list(g["columns"]),
                              ref_columns=list(g["ref_columns"]))
                         for g in self._orig_fks]
            self._fill_columns(snapshot["columns"])
            self._refresh_indexes_grid()
            self._refresh_fk_grid()
            self.sql_preview.setPlainText("# 服务器当前 DDL：\n" + snapshot["create_sql"])
            self.status_label.setText(f"已加载：{len(snapshot['columns'])} 列 · "
                                      f"{len(snapshot['indexes'])} 条索引记录")
            self.btn_apply.setEnabled(True)

        run_async(fetch, done, lambda err: self.status_label.setText(f"加载失败：{err}"))

    # ---- 索引管理 ----
    def _refresh_indexes_grid(self) -> None:
        rows = []
        for g in self._indexes:
            if str(g["index_name"]).upper() == "PRIMARY":
                kind = "主键"
            elif _falsy(g.get("non_unique")):
                kind = "UNIQUE"
            else:
                kind = "普通"
            rows.append((g["index_name"], kind, ", ".join(g["columns"])))
        self._fill_readonly(self.indexes_grid, rows)

    def _add_index(self) -> None:
        if self.new_table:
            self.status_label.setText("新建表模式暂不提供索引编辑，创建后再设计索引。")
            return
        cols = [c["name"] for c in self._read_columns()]
        if not cols:
            self.status_label.setText("没有可索引的列。")
            return
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新增索引", "索引名：", text=f"idx_{self.table}")
        name = (name or "").strip()
        if not ok or not name:
            return
        type_text, ok2 = QInputDialog.getItem(self, "新增索引", "索引类型：",
                                              ["普通", "UNIQUE"], 0, False)
        if not ok2:
            return
        col, ok3 = QInputDialog.getItem(self, "新增索引", "索引列：", cols, 0, False)
        if not ok3 or not col:
            return
        self.add_index(name, [col], unique=(type_text == "UNIQUE"))

    def add_index(self, name: str, columns: list[str], unique: bool = False) -> None:
        """编程入口（供测试/UI 复用）：追加工作副本中的索引。"""
        if str(name).upper() == "PRIMARY":
            raise ValueError("请通过列定义维护主键")
        self._indexes.append({"index_name": name,
                              "non_unique": "0" if unique else "1",
                              "columns": list(columns)})
        self._refresh_indexes_grid()
        self._generate_preview()

    def _remove_index_selected(self) -> None:
        row = self.indexes_grid.currentRow()
        if row < 0 or row >= len(self._indexes):
            self.status_label.setText("请先选中要删除的索引行。")
            return
        name = self._indexes[row]["index_name"]
        if str(name).upper() == "PRIMARY":
            self.status_label.setText("主键需在列定义中维护（不支持删除）。")
            return
        if QMessageBox.question(self, "删除索引", f"删除索引 `{name}`？"
                                ) != QMessageBox.Yes:
            return
        del self._indexes[row]
        self._refresh_indexes_grid()
        self._generate_preview()

    def remove_index(self, name: str) -> None:
        """编程入口（供测试/UI 复用）。"""
        for i, g in enumerate(self._indexes):
            if g["index_name"] == name:
                del self._indexes[i]
                break
        self._refresh_indexes_grid()
        self._generate_preview()

    # ---- 外键管理 ----
    def _refresh_fk_grid(self) -> None:
        rows = []
        for g in self._fks:
            rows.append((g["constraint_name"], ", ".join(g["columns"]),
                         f"{g['ref_table']}({', '.join(g['ref_columns'])})",
                         f"DEL {g['on_delete']} · UPD {g['on_update'] or 'RESTRICT'}"))
        self._fill_readonly(self.fk_grid, rows)

    def _add_fk(self) -> None:
        if self.new_table:
            self.status_label.setText("新建表模式暂不提供外键编辑，创建后再设计外键。")
            return
        from PySide6.QtWidgets import QInputDialog

        from magiccat.services.metadata_service import MetadataService

        meta = MetadataService(self._connections)
        try:
            tables = [t["name"] for t in meta.tables(self.profile, self.schema)
                      if t["type"] == "BASE TABLE" and t["name"] != self.table]
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"读取可引用表失败：{exc}")
            return
        if not tables:
            self.status_label.setText("本库没有可引用的基础表。")
            return
        cols = [c["name"] for c in self._read_columns()]
        if not cols:
            self.status_label.setText("没有可作外键的列。")
            return
        name, ok = QInputDialog.getText(self, "新增外键", "约束名：",
                                        text=f"fk_{self.table}")
        name = (name or "").strip()
        if not ok or not name:
            return
        col, ok2 = QInputDialog.getItem(self, "新增外键", "本表列：", cols, 0, False)
        if not ok2:
            return
        ref_t, ok3 = QInputDialog.getItem(self, "新增外键", "引用表：", tables, 0, False)
        if not ok3:
            return
        try:
            ref_cols = [c["name"] for c in meta.columns(self.profile, self.schema, ref_t)]
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"读取引用表列失败：{exc}")
            return
        if not ref_cols:
            self.status_label.setText("引用表没有列。")
            return
        ref_col, ok4 = QInputDialog.getItem(self, "新增外键", "引用列：", ref_cols, 0, False)
        if not ok4:
            return
        rule, ok5 = QInputDialog.getItem(self, "新增外键", "ON DELETE：",
                                         ["RESTRICT", "CASCADE", "SET NULL", "NO ACTION"],
                                         0, False)
        self.add_fk(name, col, ref_t, ref_col, on_delete=rule if ok5 else "RESTRICT")

    def add_fk(self, name: str, column: str, ref_table: str, ref_column: str,
               on_delete: str = "RESTRICT", on_update: str = "RESTRICT") -> None:
        """编程入口（供测试/UI 复用）：追加外键工作副本（单列外键）。"""
        self._fks.append({"constraint_name": name, "columns": [column],
                          "ref_table": ref_table, "ref_columns": [ref_column],
                          "on_delete": on_delete, "on_update": on_update})
        self._refresh_fk_grid()
        self._generate_preview()

    def _remove_fk_selected(self) -> None:
        row = self.fk_grid.currentRow()
        if row < 0 or row >= len(self._fks):
            self.status_label.setText("请先选中要删除的外键行。")
            return
        name = self._fks[row]["constraint_name"]
        if QMessageBox.question(self, "删除外键", f"删除外键 `{name}`？"
                                ) != QMessageBox.Yes:
            return
        self.remove_fk(name)

    def remove_fk(self, name: str) -> None:
        """编程入口（供测试/UI 复用）。"""
        for i, g in enumerate(self._fks):
            if g["constraint_name"] == name:
                del self._fks[i]
                break
        self._refresh_fk_grid()
        self._generate_preview()

    @staticmethod
    def _fk_fragments(orig: list[dict], current: list[dict], schema: str) -> list[str]:
        """比较外键工作副本生成 ADD/DROP CONSTRAINT 片段（单列外键）。"""
        orig_names = {g["constraint_name"] for g in orig if g["constraint_name"]}
        cur_names = {g["constraint_name"] for g in current if g["constraint_name"]}
        frags = [f"DROP FOREIGN KEY `{n.replace('`', '``')}`"
                 for n in sorted(orig_names - cur_names)]
        cur = {g["constraint_name"]: g for g in current}
        for name in sorted(cur_names - orig_names):
            g = cur[name]
            col = g["columns"][0].replace("`", "``")
            ref_t = g["ref_table"].replace("`", "``")
            ref_c = g["ref_columns"][0].replace("`", "``")
            on_del = f" ON DELETE {g['on_delete']}" if g.get("on_delete") else ""
            on_upd = f" ON UPDATE {g['on_update']}" if g.get("on_update") else ""
            frags.append(
                f"ADD CONSTRAINT `{name.replace('`', '``')}` FOREIGN KEY (`{col}`) "
                f"REFERENCES `{schema.replace('`', '``')}`.`{ref_t}` (`{ref_c}`)"
                + on_del + on_upd)
        return frags

    @staticmethod
    def _index_fragments(orig: list[dict], current: list[dict],
                         dropped_columns: list[str] | None = None) -> list[str]:
        """比较索引工作副本，生成 ADD/DROP INDEX 片段（主键不在此管理）。

        若某列同时被删除，MySQL 会随列自动删除其索引，故跳过对应的 DROP INDEX
        以避免 “check that column/key exists” 报错。
        """
        dropped = set(dropped_columns or [])
        orig_names = {g["index_name"] for g in orig if g["index_name"] != "PRIMARY"}
        cur_names = {g["index_name"] for g in current if g["index_name"] != "PRIMARY"}
        frags: list[str] = []
        for name in sorted(orig_names - cur_names):
            colset = {c for g in orig if g["index_name"] == name for c in g["columns"]}
            if colset & dropped:
                continue  # 索引随列删除而删除
            frags.append(f"DROP INDEX `{name.replace('`', '``')}`")
        cur = {g["index_name"]: g for g in current}
        for name in sorted(cur_names - orig_names):
            g = cur[name]
            unique = "UNIQUE " if _falsy(g.get("non_unique")) else ""
            cols = ", ".join(f"`{c.replace('`', '``')}`" for c in g["columns"])
            frags.append(f"ADD {unique}INDEX `{name.replace('`', '``')}` ({cols})")
        return frags

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
        if self.new_table:
            if not edited:
                return None
            from magiccat.services.ddl_builder import build_create

            return build_create(self.schema, self.table, edited)
        frags = alter_fragments(self._orig_columns, edited)
        dropped_cols = [c["name"] for c in self._orig_columns
                        if c["name"] not in {e["name"] for e in edited}]
        frags += self._index_fragments(self._orig_indexes, self._indexes, dropped_cols)
        frags += self._fk_fragments(self._orig_fks, self._fks, self.schema)
        if not frags:
            return None
        from magiccat.services.ddl_builder import _q

        head = f"ALTER TABLE {_q(self.schema)}.{_q(self.table)} "
        return ";\n".join(head + f for f in frags)

    def _generate_preview(self) -> None:
        edited = self._read_columns()
        sql = self._build_sql(edited)
        if sql is None:
            if self.new_table:
                self.status_label.setText("请至少填写一列（列名 + 类型）")
            else:
                self.sql_preview.setPlainText(
                    "# 服务器当前 DDL：\n" + self._snapshot.get("create_sql", "")
                    + "\n\n# 未检测到列变更")
                self.status_label.setText("未检测到列变更")
            return
        if self.new_table:
            self.sql_preview.setPlainText("# CREATE TABLE 预览（将执行）：\n" + sql + ";")
            self.status_label.setText(f"预览就绪：{len(edited)} 列")
        else:
            self.sql_preview.setPlainText(
                "# 服务器当前 DDL：\n" + self._snapshot.get("create_sql", "")
                + "\n\n# 变更预览（将执行）：\n" + sql + ";")
            self.status_label.setText(
                f"预览就绪：{len(edited)} 列，{sql.count('COLUMN')} 处变更")

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
            QMessageBox.critical(self, "应用变更", "\n".join(e["message"] for e in errors))
            self.btn_apply.setEnabled(True)
            return
        verb = "创建" if self.new_table else "变更"
        QMessageBox.information(self, "应用变更", f"{verb}成功（{len(results)} 条语句）。")
        if self.new_table:
            self.new_table = False  # 创建成功后转为“编辑已有表”模式
        self._load()

    def _after_apply_error(self, err: str) -> None:
        self.btn_apply.setEnabled(True)
        QMessageBox.critical(self, "应用变更", f"执行失败：{err}")
        self.status_label.setText("应用失败")


def _falsy(v) -> bool:
    return v in (0, "0", False, "false", "no", "NO")
