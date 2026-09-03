"""对象浏览器树（M2）：分组 → 连接 → 数据库 → [表/视图/例程/触发器] → 列。

懒加载策略：可展开节点只放一个占位子项；展开时在后台线程拉元数据
（run_async），完成后在主线程替换为真实子项 —— 浏览不卡 UI。
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.metadata_service import MetadataService
from magiccat.ui.dialogs import ConnectionEditDialog
from magiccat.ui.job import run_async

logger = logging.getLogger(__name__)

KIND_KEY = "kind"  # 存于 Qt.UserRole 的字典键
DATA_KEY = "data"

KIND_PLACEHOLDER = "placeholder"
KIND_ERROR = "error"


def _info(item: QTreeWidgetItem) -> dict[str, Any]:
    return item.data(0, Qt.UserRole) or {}


def _make_item(text: str, kind: str, **extra: Any) -> QTreeWidgetItem:
    from magiccat.ui.icons import icon

    item = QTreeWidgetItem([text])
    item.setData(0, Qt.UserRole, {KIND_KEY: kind, DATA_KEY: extra})
    item.setIcon(0, icon(kind, extra.get("type", "") or extra.get("kind", "")))
    return item


def _placeholder(parent: QTreeWidgetItem) -> QTreeWidgetItem:
    p = QTreeWidgetItem(["…"])
    p.setData(0, Qt.UserRole, {KIND_KEY: KIND_PLACEHOLDER})
    p.setFlags(p.flags() & ~Qt.ItemIsSelectable)
    parent.addChild(p)
    return p


def _replace_children(parent: QTreeWidgetItem, children: list[QTreeWidgetItem]) -> None:
    try:
        parent.takeChildren()
    except RuntimeError:
        return  # 节点已被删除（如连接关闭）
    for c in children:
        parent.addChild(c)


class ObjectExplorer(QTreeWidget):
    """连接与数据库对象导航树。"""

    open_table_requested = Signal(str, str, str)  # profile_id, schema, table
    design_table_requested = Signal(str, str, str)  # profile_id, schema, table
    er_database_requested = Signal(str, str)  # profile_id, schema
    create_table_requested = Signal(str, str)  # profile_id, schema
    open_saved_query = Signal(str, str)  # profile_id, name
    create_routine_requested = Signal(str, str, str, str)  # profile_id, schema, kind, name
    create_routine_entry = Signal(str, str)  # profile_id, schema（弹向导）
    open_routine_sql = Signal(str, str, str)  # profile_id, name, sql_text
    selection_info_requested = Signal(object)  # 当前选中项描述 dict
    domain_selected = Signal(str, str, str)  # profile_id, schema, cat_type（`对象`页联动）

    def __init__(self, connections: ConnectionService, metadata: MetadataService,
                 parent=None) -> None:
        super().__init__(parent)
        self._connections = connections
        self._metadata = metadata
        from magiccat.services.query_library import QueryLibrary

        self._queries = QueryLibrary.default()
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.itemExpanded.connect(self._on_expanded)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        self.currentItemChanged.connect(self._on_selection_changed)

    # ---- 选中项信息（信息面板联动） ----
    def _on_selection_changed(self, current: QTreeWidgetItem | None,
                              _previous: QTreeWidgetItem | None = None) -> None:
        if current is None:
            return
        info = _info(current)
        kind = info.get(KIND_KEY)
        data = info.get(DATA_KEY, {})
        if kind == "profile":
            desc = {"kind": "profile", "profile_id": data.get("profile_id")}
        else:
            profile = self._profile_of(current)
            if profile is None:
                return
            pid = profile.id
            if kind == "database":
                desc = {"kind": "database", "profile_id": pid, "schema": data.get("schema")}
            elif kind in ("table", "view"):
                desc = {"kind": kind, "profile_id": pid, "schema": data.get("schema"),
                        "table": data.get("table"), "name": data.get("name")}
            elif kind == "routine":
                desc = {"kind": "routine", "profile_id": pid, "schema": data.get("schema"),
                        "name": data.get("name"), "type": data.get("type", "")}
            elif kind == "trigger":
                desc = {"kind": "trigger", "profile_id": pid, "schema": data.get("schema"),
                        "name": data.get("name")}
            elif kind == "column":
                desc = {"kind": "column", "profile_id": pid, "schema": data.get("schema"),
                        "name": data.get("name"),
                        "data_type": data.get("data_type", ""),
                        "nullable": data.get("nullable", ""),
                        "default": data.get("default_value", ""),
                        "comment": data.get("comment", "")}
            elif kind == "group":
                desc = {"kind": "group", "name": current.text(0)}
            elif kind == "category":
                desc = {"kind": "category", "name": current.text(0)}
                cat_type = data.get("cat_type")
                if cat_type:
                    self.domain_selected.emit(pid, data.get("schema", ""), cat_type)
            elif kind == "saved_query":
                desc = {"kind": "saved_query", "profile_id": pid,
                        "schema": data.get("schema"), "name": data.get("name")}
            else:
                return
        self.selection_info_requested.emit(desc)

    # ---- 装载 ----
    def load_profiles(self) -> None:
        """重建整树（分组 → 连接）。本地配置读取，同步执行。"""
        self.clear()
        by_group: dict[str, list[ConnectionProfile]] = {}
        for p in self._connections.profiles:
            by_group.setdefault(p.group, []).append(p)
        for group, profiles in by_group.items():
            group_item = _make_item(group, "group")
            self.addTopLevelItem(group_item)
            for profile in profiles:
                self._add_profile_item(group_item, profile)
            group_item.setExpanded(True)

    def _add_profile_item(self, parent: QTreeWidgetItem, profile: ConnectionProfile) -> None:
        item = _make_item(profile.display_name, "profile", profile_id=profile.id)
        _placeholder(item)
        parent.addChild(item)

    def profile_item(self, profile_id: str) -> QTreeWidgetItem | None:
        for item in self._walk():
            info = _info(item)
            if info.get(KIND_KEY) == "profile" and info.get(DATA_KEY, {}).get("profile_id") == profile_id:
                return item
        return None

    def _walk(self):
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            if item is None:
                continue
            yield item
            stack[:0] = [item.child(i) for i in range(item.childCount())]

    # ---- 展开加载 ----
    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        info = _info(item)
        kind = info.get(KIND_KEY)
        if kind == "profile":
            self._load_profile(item)
        elif kind == "database":
            self._load_database(item)
        elif kind == "category":
            # 逐层懒加载：展开分类才取该层数据
            self._load_category(item)
        elif kind == "table" or kind == "view":
            self._load_columns(item)

    def _load_profile(self, item: QTreeWidgetItem) -> None:
        info = _info(item)
        profile = self._connections.get(info[DATA_KEY]["profile_id"])
        if profile is None:
            _replace_children(item, [_make_item("连接配置不存在", KIND_ERROR)])
            return

        def fetch() -> tuple[str, list[dict]]:
            if not self._connections.is_open(profile.id):
                self._connections.open(profile)  # 首次展开自动打开
            return profile.id, self._metadata.databases(profile)

        def done(payload: tuple[str, list[dict]]) -> None:
            if item.treeWidget() is None:
                return
            _profile_id, dbs = payload
            children = [_make_item(db["name"], "database", schema=db["name"]) for db in dbs]
            for c in children:
                _placeholder(c)
            _replace_children(item, children)
            item.setToolTip(0, f"{len(dbs)} 个数据库")

        run_async(fetch, done, lambda err: self._show_error(item, f"连接失败：{err}"))

    def refresh_schema_queries(self, profile_id: str, schema: str) -> None:
        """保存/删除查询后刷新【库级】“查询”分类（连接级无查询节点，与 Navicat 一致）。"""
        for item in self._walk():
            info = _info(item)
            data = info.get(DATA_KEY, {})
            if (info.get(KIND_KEY) == "category"
                    and data.get("cat_type") == "queries"
                    and data.get("schema") == schema):
                _replace_children(item, [
                    _make_item(q["name"], "saved_query", profile_id=profile_id,
                               name=q["name"], schema=q.get("schema", ""))
                    for q in self._queries.list(profile_id)
                    if (q.get("schema") or "") == schema])
                return
                return

    def _load_database(self, item: QTreeWidgetItem) -> None:
        """展开库：只建分类骨架（表/视图/函数/触发器/查询），数据懒加载到各分类展开时。"""
        info = _info(item)
        schema = info[DATA_KEY]["schema"]
        profile = self._profile_of(item)
        if profile is None:
            return

        children: list[QTreeWidgetItem] = []
        for label, cat_type in (("表", "tables"), ("视图", "views"), ("函数", "routines"),
                                ("触发器", "triggers")):
            cat = _make_item(label, "category", schema=schema, cat_type=cat_type)
            # 占位子项使分类可展开；展开时才拉取该层数据（逐层懒加载，避免 N+1）
            _placeholder(cat)
            children.append(cat)
        # 查询：本地具名查询，立即填充（无数据库交互）
        cat = _make_item("查询", "category", schema=schema, cat_type="queries")
        children.append(cat)
        for q in self._queries.list(profile.id):
            if (q.get("schema") or "") == schema:
                cat.addChild(_make_item(q["name"], "saved_query", profile_id=profile.id,
                                        name=q["name"], schema=q.get("schema", "")))
        _replace_children(item, children)

    def _schema_of(self, item: QTreeWidgetItem) -> str | None:
        cur: QTreeWidgetItem | None = item
        while cur is not None:
            info = _info(cur)
            if info.get(KIND_KEY) == "database":
                return info.get(DATA_KEY, {}).get("schema")
            cur = cur.parent()
        return None

    def _load_category(self, item: QTreeWidgetItem) -> None:
        """展开分类：按 cat_type 拉取并填充该层对象（单次查询，非逐对象）。"""
        info = _info(item)
        cat_type = info.get(DATA_KEY, {}).get("cat_type")
        schema = self._schema_of(item)
        profile = self._profile_of(item)
        if profile is None or not schema:
            return

        def fetch() -> list:
            if cat_type == "tables":
                return [t for t in self._metadata.tables(profile, schema)
                        if t["type"] == "BASE TABLE"]
            if cat_type == "views":
                return [v for v in self._metadata.tables(profile, schema)
                        if v["type"] == "VIEW"]
            if cat_type == "routines":
                return self._metadata.routines(profile, schema)
            if cat_type == "triggers":
                return self._metadata.triggers(profile, schema)
            return []

        def done(objects: list) -> None:
            if item.treeWidget() is None:
                return
            _replace_children(item, [self._category_leaf(o, cat_type, schema) for o in objects])

        run_async(fetch, done, lambda err: self._show_error(item, f"读取失败：{err}"))

    @staticmethod
    def _category_leaf(obj: dict, cat_type: str, schema: str) -> QTreeWidgetItem:
        if cat_type in ("tables", "views"):
            leaf = _make_item(obj["name"], "view" if cat_type == "views" else "table",
                              schema=schema, table=obj["name"], name=obj["name"])
            if cat_type == "tables":
                _placeholder(leaf)  # 表可继续展开列（列也是懒加载）
            return leaf
        if cat_type == "routines":
            return _make_item(obj["name"], "routine", schema=schema,
                              routine=obj["name"], name=obj["name"],
                              type=obj["type"].upper())
        if cat_type == "triggers":
            return _make_item(
                f"{obj['name']} [{obj['event']} ON {obj['table']}]", "trigger",
                schema=schema, name=obj["name"])
        return _make_item(str(obj.get("name", "")), "category")

    def _load_columns(self, item: QTreeWidgetItem) -> None:
        info = _info(item)
        schema, table = info[DATA_KEY]["schema"], info[DATA_KEY]["table"]
        profile = self._profile_of(item)
        if profile is None:
            return

        def fetch() -> list[dict]:
            return self._metadata.columns(profile, schema, table)

        def done(cols: list[dict]) -> None:
            if item.treeWidget() is None:
                return
            children = []
            for c in cols:
                tip = (f"{c.get('data_type')} · nullable={c.get('nullable')}"
                       f" · default={c.get('default_value')} · extra={c.get('extra')}"
                       f" · comment={c.get('comment') or '-'}")
                leaf = _make_item(f"{c['name']}  {c['data_type']}", "column",
                                  schema=schema, name=c["name"],
                                  data_type=c.get("data_type", ""),
                                  nullable=c.get("nullable", ""),
                                  default_value=c.get("default_value") or "",
                                  comment=c.get("comment") or "")
                leaf.setToolTip(0, tip)
                children.append(leaf)
            _replace_children(item, children)

        run_async(fetch, done, lambda err: self._show_error(item, f"读取失败：{err}"))

    def _profile_of(self, item: QTreeWidgetItem) -> ConnectionProfile | None:
        """向上找所属连接。"""
        cur: QTreeWidgetItem | None = item
        while cur is not None:
            info = _info(cur)
            if info.get(KIND_KEY) == "profile":
                return self._connections.get(info[DATA_KEY]["profile_id"])
            cur = cur.parent()
        return None

    def _show_error(self, item: QTreeWidgetItem, message: str) -> None:
        if item.treeWidget() is None:
            return
        _replace_children(item, [_make_item(message, KIND_ERROR)])

    # ---- 过滤 ----
    def apply_name_filter(self, text: str) -> None:
        """按名称过滤整棵树：节点自身或任意后代命中则保持可见（不自动展开/加载）。"""
        keyword = text.strip().lower()
        for i in range(self.topLevelItemCount()):
            self._apply_filter(self.topLevelItem(i), keyword)

    @staticmethod
    def _apply_filter(item: QTreeWidgetItem, keyword: str) -> bool:
        if keyword == "":
            item.setHidden(False)
            for c in range(item.childCount()):
                ObjectExplorer._apply_filter(item.child(c), keyword)
            return True
        self_hit = keyword in item.text(0).lower()
        any_child_hit = False
        for c in range(item.childCount()):
            if ObjectExplorer._apply_filter(item.child(c), keyword):
                any_child_hit = True
        visible = self_hit or any_child_hit
        item.setHidden(not visible)
        return visible

    # ---- 交互 ----
    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        info = _info(item)
        kind = info.get(KIND_KEY)
        if kind == "profile":
            item.setExpanded(not item.isExpanded())
        elif kind == "saved_query":
            self._open_saved_query_item(item)
        elif kind == "routine":
            self._open_routine_sql(item)
        elif kind in ("table", "view"):
            profile = self._profile_of(item)
            if profile is not None:
                self.open_table_requested.emit(
                    profile.id, info[DATA_KEY]["schema"], info[DATA_KEY]["table"])
        elif kind == "database":
            item.setExpanded(not item.isExpanded())

    def _show_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        info = _info(item)
        kind = info.get(KIND_KEY)
        profile = self._profile_of(item) if kind not in ("group", "category", KIND_ERROR,
                                                         KIND_PLACEHOLDER) else None

        menu = QMenu(self)
        action_test = action_open = action_close = None
        action_refresh = action_edit = action_delete = action_design = None
        action_er = action_new_table = action_new_db = None
        action_truncate = action_drop = action_copy_ddl = None
        action_obj_copy = action_obj_drop = None
        action_open_query = action_del_query = None
        action_run_sql = action_new_routine = action_edit_db = None

        if kind == "profile":
            action_test = menu.addAction("测试连接")
            if self._connections.is_open(profile.id):
                action_close = menu.addAction("关闭连接")
            else:
                action_open = menu.addAction("打开连接")
            action_refresh = menu.addAction("刷新")
            menu.addSeparator()
            action_edit = menu.addAction("编辑连接…")
            action_delete = menu.addAction("删除连接…")
        elif kind in ("database", "table", "view", "routine", "trigger", "category"):
            action_refresh = menu.addAction("刷新")
        if kind == "table":
            action_design = menu.addAction("设计表…")
            action_copy_ddl = menu.addAction("复制 CREATE 语句…")
            menu.addSeparator()
            action_truncate = menu.addAction("清空表…")
            action_drop = menu.addAction("删除表…")
        if kind == "saved_query":
            action_open_query = menu.addAction("打开")
            action_del_query = menu.addAction("删除…")
        if kind == "category" and item.text(0).startswith("函数"):
            action_new_routine = menu.addAction("新建函数…")
        if kind in ("view", "routine", "trigger"):
            action_obj_copy = menu.addAction("复制 CREATE 语句…")
            action_obj_drop = menu.addAction("删除对象…")
        if kind == "database":
            action_run_sql = menu.addAction("运行 SQL 文件…")
            action_new_routine = menu.addAction("新建函数…")
            action_er = menu.addAction("查看 ER 图…")
            menu.addSeparator()
            action_new_table = menu.addAction("新建表…")
            action_new_db = menu.addAction("新建数据库…")
            action_edit_db = menu.addAction("编辑数据库…")
            menu.addSeparator()
            dump_menu = menu.addMenu("转储 SQL 文件…")
            act_dump_all = dump_menu.addAction("结构和数据…")
            act_dump_schema = dump_menu.addAction("仅结构…")

        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is action_test:
            self._run_profile_action(profile, self._connections.test, "测试成功：")
        elif chosen is action_open:
            self._run_profile_action(profile, self._connections.open, "已打开：")
        elif chosen is action_close:
            self._close_profile(profile)
        elif chosen is action_refresh:
            self._refresh_item(item)
        elif chosen is action_edit:
            self._edit_profile(profile)
        elif chosen is action_delete:
            self._delete_profile(profile)
        elif chosen is action_design:
            self._design_table(item)
        elif chosen is action_copy_ddl:
            self._copy_create_sql(item)
        elif chosen is action_er:
            self._er_database(item)
        elif chosen is action_run_sql:
            self._run_sql_file(item)
        elif chosen is act_dump_all:
            self._dump_database(item, with_data=True)
        elif chosen is act_dump_schema:
            self._dump_database(item, with_data=False)
        elif chosen is action_new_table:
            self._new_table(item)
        elif chosen is action_new_db:
            self._new_database(item)
        elif chosen is action_new_routine:
            self._new_routine(item)
        elif chosen is action_edit_db:
            self._edit_database(item)
        elif chosen is action_truncate or chosen is action_drop:
            self._drop_or_truncate_table(item, truncate=chosen is action_truncate)
        elif chosen is action_obj_copy:
            self._copy_object_ddl(item)
        elif chosen is action_obj_drop:
            self._drop_object(item)
        elif chosen is action_open_query:
            self._open_saved_query_item(item)
        elif chosen is action_del_query:
            self._delete_saved_query(item)

    def _edit_database(self, item: QTreeWidgetItem) -> None:
        from magiccat.ui.database_dialog import EditDatabaseDialog

        info = _info(item)
        profile = self._profile_of(item)
        if profile is None:
            return
        EditDatabaseDialog(profile, info[DATA_KEY]["schema"], self._connections, self).exec()

    def _er_database(self, item: QTreeWidgetItem) -> None:
        info = _info(item)
        profile = self._profile_of(item)
        if profile is not None:
            self.er_database_requested.emit(profile.id, info[DATA_KEY]["schema"])

    def _design_table(self, item: QTreeWidgetItem) -> None:
        info = _info(item)
        profile = self._profile_of(item)
        if profile is None:
            return
        self.design_table_requested.emit(
            profile.id, info[DATA_KEY]["schema"], info[DATA_KEY]["table"])

    def _copy_create_sql(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QMessageBox

        from magiccat.services.ddl_service import DdlService

        info = _info(item)
        profile = self._profile_of(item)
        if profile is None:
            return
        schema, table = info[DATA_KEY]["schema"], info[DATA_KEY]["table"]
        ddl = DdlService(self._connections)

        def done(create_sql: str) -> None:
            QGuiApplication.clipboard().setText(create_sql)
            QMessageBox.information(self, "复制 CREATE", f"已复制到剪贴板（{len(create_sql)} 字符）。")

        run_async(lambda: ddl.show_create(profile, schema, table), done,
                  lambda err: QMessageBox.warning(self, "复制 CREATE", f"失败：{err}"))

    # ---- 对象管理动作 ----
    def refresh_schema(self, profile_id: str, schema: str) -> None:
        """刷新指定库的子树（供外部在 DDL 操作后调用）。"""
        for item in self._walk():
            info = _info(item)
            if (info.get(KIND_KEY) == "database"
                    and info.get(DATA_KEY, {}).get("schema") == schema
                    and self._profile_of(item) is not None
                    and self._profile_of(item).id == profile_id):
                self._load_database(item)
                return

    def _new_table(self, item: QTreeWidgetItem) -> None:
        info = _info(item)
        profile = self._profile_of(item)
        if profile is not None:
            self.create_table_requested.emit(profile.id, info[DATA_KEY]["schema"])

    def _new_routine(self, item: QTreeWidgetItem) -> None:
        """「新建函数…」：向上找到所属库，交由主窗口弹函数向导。"""
        profile = self._profile_of(item)
        if profile is None:
            return
        schema = None
        cur: QTreeWidgetItem | None = item
        while cur is not None:
            info = _info(cur)
            if info.get(KIND_KEY) == "database":
                schema = info.get(DATA_KEY, {}).get("schema")
                break
            cur = cur.parent()
        if schema:
            self.create_routine_entry.emit(profile.id, schema)

    def _new_database(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        from magiccat.services.query_service import QueryService

        profile = self._profile_of(item)
        if profile is None:
            return
        name, ok = QInputDialog.getText(self, "新建数据库", "数据库名称：")
        name = (name or "").strip()
        if not ok or not name:
            return
        import re

        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            QMessageBox.warning(self, "新建数据库", "名称只能包含字母/数字/下划线。")
            return
        sql = f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
        query = QueryService(self._connections)

        def done(results: list[dict]) -> None:
            errors = [r for r in results if r.get("kind") == "error"]
            if errors:
                QMessageBox.warning(self, "新建数据库", errors[0]["message"])
                return
            QMessageBox.information(self, "新建数据库", f"数据库 `{name}` 创建成功。")
            profile_item = self.profile_item(profile.id)
            if profile_item is not None:
                self._load_profile(profile_item)

        run_async(lambda: query.execute(profile, sql), done,
                  lambda err: QMessageBox.critical(self, "新建数据库", err))

    def _drop_or_truncate_table(self, item: QTreeWidgetItem, truncate: bool) -> None:
        from PySide6.QtWidgets import QMessageBox

        from magiccat.services.query_service import QueryService

        info = _info(item)
        schema, table = info[DATA_KEY]["schema"], info[DATA_KEY]["table"]
        profile = self._profile_of(item)
        if profile is None:
            return
        verb = "清空" if truncate else "删除"
        action_sql = (f"TRUNCATE TABLE `{schema}`.`{table}`"
                      if truncate else f"DROP TABLE `{schema}`.`{table}`")
        if QMessageBox.question(
                self, f"{verb}表",
                f"确定{verb}表 `{schema}`.{table}？\n\n{action_sql}",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        query = QueryService(self._connections)

        def done(results: list[dict]) -> None:
            errors = [r for r in results if r.get("kind") == "error"]
            if errors:
                QMessageBox.warning(self, f"{verb}表", errors[0]["message"])
                return
            # 刷新父级数据库节点
            db_item = item.parent().parent() if item.parent() else None
            while db_item is not None and _info(db_item).get(KIND_KEY) != "database":
                db_item = db_item.parent()
            if db_item is not None:
                self._load_database(db_item)

        run_async(lambda: query.execute(profile, action_sql), done,
                  lambda err: QMessageBox.critical(self, f"{verb}表", err))

    def _copy_object_ddl(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QMessageBox

        from magiccat.services.ddl_service import DdlService

        info = _info(item)
        kind = info.get(KIND_KEY)
        data = info.get(DATA_KEY, {})
        profile = self._profile_of(item)
        if profile is None or not data.get("name"):
            return
        schema, name = data["schema"], data["name"]
        ddl = DdlService(self._connections)

        def fetch() -> str:
            if kind == "view":
                return ddl.show_create_view(profile, schema, name)
            if kind == "routine":
                return ddl.show_create_routine(profile, schema, name,
                                               data.get("type", "PROCEDURE"))
            return ddl.show_create_trigger(profile, schema, name)

        def done(sql: str) -> None:
            QGuiApplication.clipboard().setText(sql)
            QMessageBox.information(self, "复制 CREATE",
                                    f"已复制到剪贴板（{len(sql)} 字符）。")

        run_async(fetch, done,
                  lambda err: QMessageBox.warning(self, "复制 CREATE", f"失败：{err}"))

    def _drop_object(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QMessageBox

        from magiccat.services.query_service import QueryService

        info = _info(item)
        kind = info.get(KIND_KEY)
        data = info.get(DATA_KEY, {})
        profile = self._profile_of(item)
        if profile is None or not data.get("name"):
            return
        if kind == "view":
            word = "VIEW"
        elif kind == "trigger":
            word = "TRIGGER"
        elif kind == "routine":
            word = data.get("type", "PROCEDURE")
        else:
            return
        schema, name = data["schema"], data["name"]
        sql = f"DROP {word} IF EXISTS `{schema}`.`{name}`"
        if QMessageBox.question(
                self, "删除对象", f"确定删除 {word} `{schema}`.{name}？\n\n{sql}",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        query = QueryService(self._connections)

        def done(results: list[dict]) -> None:
            errors = [r for r in results if r.get("kind") == "error"]
            if errors:
                QMessageBox.warning(self, "删除对象", errors[0]["message"])
                return
            db_item = item.parent().parent() if item.parent() else None
            while db_item is not None and _info(db_item).get(KIND_KEY) != "database":
                db_item = db_item.parent()
            if db_item is not None:
                self._load_database(db_item)

        run_async(lambda: query.execute(profile, sql), done,
                  lambda err: QMessageBox.critical(self, "删除对象", err))

    def _open_routine_sql(self, item: QTreeWidgetItem) -> None:
        """双击“函数”节点：取 SHOW CREATE 的例程定义 SQL，交由主窗口打开编辑器。"""
        from magiccat.services.ddl_service import DdlService

        info = _info(item)
        data = info.get(DATA_KEY, {})
        profile = self._profile_of(item)
        if profile is None or not data.get("name"):
            return
        schema, name = data.get("schema"), data.get("name")
        kind = data.get("type", "PROCEDURE")
        ddl = DdlService(self._connections)

        def done(sql_text: str) -> None:
            self.open_routine_sql.emit(profile.id, name, sql_text)

        run_async(lambda: ddl.show_create_routine(profile, schema, name, kind), done,
                  lambda err: logger.warning("读取函数定义失败: %s", err))

    def _open_saved_query_item(self, item: QTreeWidgetItem) -> None:
        info = _info(item)
        data = info.get(DATA_KEY, {})
        if data.get("profile_id") and data.get("name"):
            self.open_saved_query.emit(data["profile_id"], data["name"])

    def _delete_saved_query(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QMessageBox

        info = _info(item)
        data = info.get(DATA_KEY, {})
        name = data.get("name")
        profile_id = data.get("profile_id")
        if not name or not profile_id:
            return
        if QMessageBox.question(self, "删除查询", f"删除查询「{name}」？"
                                ) != QMessageBox.Yes:
            return
        self._queries.delete(profile_id, name)
        # 刷新其所属库的“查询”分类
        schema = (item.parent().data(0, 0x0100) or {}).get("data", {}).get("schema") if item.parent() else None
        if schema:
            self.refresh_schema_queries(profile_id, schema)

    def _dump_database(self, item: QTreeWidgetItem, with_data: bool) -> None:
        """转储整个数据库为 SQL 文件（对标 Navicat：结构和数据 / 仅结构）。"""
        import threading
        from pathlib import Path

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

        from magiccat.services import backup
        from magiccat.services.data_service import DataService
        from magiccat.services.ddl_service import DdlService

        info = _info(item)
        schema = info[DATA_KEY]["schema"]
        profile = self._profile_of(item)
        if profile is None:
            return
        path, _f = QFileDialog.getSaveFileName(self, "转储 SQL 文件", f"{schema}.sql",
                                               "SQL 脚本 (*.sql)")
        if not path:
            return
        ev = threading.Event()
        dialog = QProgressDialog("正在转储…", "取消", 0, 0, self)
        dialog.setWindowTitle(f"转储 {schema}")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(300)
        dialog.canceled.connect(ev.set)
        dialog.setValue(0)

        def fetch() -> dict:
            return backup.dump_schema_sql(
                profile, schema, Path(path), DataService(self._connections),
                MetadataService(self._connections), DdlService(self._connections),
                cancel=ev, with_data=with_data)

        def done(res: dict) -> None:
            dialog.close()
            if res.get("cancelled"):
                QMessageBox.information(self, "转储", "已取消。")
                return
            rows_note = f" · {res['rows']} 行数据" if with_data else "（仅结构）"
            QMessageBox.information(
                self, "转储",
                f"完成：{res['tables']} 表 / {res['views']} 视图 / "
                f"{res['routines']} 函数 / {res['triggers']} 触发器{rows_note} →\n{path}")

        def error(err: str) -> None:
            dialog.close()
            if "TransferCancelled" in err:
                QMessageBox.information(self, "转储", "已取消。")
            else:
                QMessageBox.critical(self, "转储", f"失败：{err}")

        run_async(fetch, done, error)

    def _run_sql_file(self, item: QTreeWidgetItem) -> None:
        """运行 SQL 文件（以当前库为默认目标；未加库前缀的语句落到该库）。"""
        from pathlib import Path

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

        from magiccat.services import backup
        from magiccat.services.query_service import QueryService

        info = _info(item)
        schema = info[DATA_KEY]["schema"]
        profile = self._profile_of(item)
        if profile is None:
            return
        path, _f = QFileDialog.getOpenFileName(self, "运行 SQL 文件", "",
                                               "SQL 脚本 (*.sql);;所有文件 (*)")
        if not path:
            return
        dialog = QProgressDialog("正在执行 SQL 文件…", None, 0, 0, self)
        dialog.setWindowTitle(f"运行 SQL 文件 · {schema}")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(300)
        dialog.setValue(0)

        def fetch() -> dict:
            return backup.restore_sql_file(profile, Path(path),
                                           QueryService(self._connections), schema=schema)

        def done(res: dict) -> None:
            dialog.close()
            if res["ok"]:
                QMessageBox.information(self, "运行 SQL 文件",
                                        f"完成：{res['statements']} 条语句执行成功。")
            else:
                QMessageBox.warning(
                    self, "运行 SQL 文件",
                    f"{res['statements']} 条语句中 {len(res['errors'])} 条失败：\n"
                    + "\n".join(res["errors"]))

        def error(err: str) -> None:
            dialog.close()
            QMessageBox.critical(self, "运行 SQL 文件", f"失败：{err}")

        run_async(fetch, done, error)

    def _run_profile_action(self, profile: ConnectionProfile, fn, prefix: str) -> None:
        item = self.profile_item(profile.id)
        if item is not None:
            _replace_children(item, [_make_item("处理中…", KIND_PLACEHOLDER)])
        run_async(lambda: fn(profile),
                  lambda version: self._after_profile_action(profile, f"{prefix}{version}"),
                  lambda err: self._after_profile_action(profile, f"失败：{err}"))

    def _after_profile_action(self, profile: ConnectionProfile, message: str) -> None:
        item = self.profile_item(profile.id)
        if item is None:
            return
        if self._connections.is_open(profile.id):
            info = _info(item)
            info["opened"] = True
            item.setData(0, Qt.UserRole, info)
            item.setText(0, f"{profile.display_name}  ●")
            self._load_profile(item)
        item.setToolTip(0, message)
        logger.info("%s [%s] %s", profile.name, profile.host, message)

    def _close_profile(self, profile: ConnectionProfile) -> None:
        self._connections.close(profile.id)
        item = self.profile_item(profile.id)
        if item is not None:
            _replace_children(item, [_make_item("…", KIND_PLACEHOLDER)])
            item.setText(0, profile.display_name)
            item.setToolTip(0, "")

    def _refresh_item(self, item: QTreeWidgetItem) -> None:
        info = _info(item)
        kind = info.get(KIND_KEY)
        if kind == "profile":
            self._load_profile(item)
        elif kind == "database":
            self._load_database(item)
        elif kind in ("table", "view"):
            self._load_columns(item)
        elif kind == "category":
            parent = item.parent()
            if parent is not None:
                info_p = _info(parent)
                if info_p.get(KIND_KEY) == "database":
                    self._load_database(parent)

    def _edit_profile(self, profile: ConnectionProfile) -> None:
        dialog = ConnectionEditDialog(self, profile, self._connections.groups)
        if dialog.exec():
            edited = dialog.profile()
            edited.id = profile.id
            self._connections.update(edited)
            self.load_profiles()
            if self._connections.is_open(edited.id):
                self._connections.close(edited.id)

    def _delete_profile(self, profile: ConnectionProfile) -> None:
        from PySide6.QtWidgets import QMessageBox

        if QMessageBox.question(
                self, "删除连接", f"确定删除连接「{profile.name}」？",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._connections.remove(profile.id)
            self.load_profiles()
