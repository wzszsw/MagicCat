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
    item = QTreeWidgetItem([text])
    item.setData(0, Qt.UserRole, {KIND_KEY: kind, DATA_KEY: extra})
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

    def __init__(self, connections: ConnectionService, metadata: MetadataService,
                 parent=None) -> None:
        super().__init__(parent)
        self._connections = connections
        self._metadata = metadata
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.itemExpanded.connect(self._on_expanded)
        self.itemDoubleClicked.connect(self._on_double_clicked)

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
            _, dbs = payload
            children = [_make_item(db["name"], "database", schema=db["name"]) for db in dbs]
            for c in children:
                _placeholder(c)
            _replace_children(item, children)
            item.setToolTip(0, f"{len(dbs)} 个数据库")

        run_async(fetch, done, lambda err: self._show_error(item, f"连接失败：{err}"))

    def _load_database(self, item: QTreeWidgetItem) -> None:
        info = _info(item)
        schema = info[DATA_KEY]["schema"]
        profile = self._profile_of(item)
        if profile is None:
            return

        def fetch() -> dict:
            tables = self._metadata.tables(profile, schema)
            routines = self._metadata.routines(profile, schema)
            triggers = self._metadata.triggers(profile, schema)
            return {"tables": tables, "routines": routines, "triggers": triggers}

        def done(data: dict) -> None:
            if item.treeWidget() is None:
                return
            children: list[QTreeWidgetItem] = []
            tables = [t for t in data["tables"] if t["type"] == "BASE TABLE"]
            views = [v for v in data["tables"] if v["type"] == "VIEW"]
            if tables:
                cat = _make_item(f"表 ({len(tables)})", "category")
                children.append(cat)
                for t in tables:
                    ti = _make_item(t["name"], "table", schema=schema, table=t["name"])
                    _placeholder(ti)
                    cat.addChild(ti)
            if views:
                cat = _make_item(f"视图 ({len(views)})", "category")
                children.append(cat)
                for v in views:
                    cat.addChild(_make_item(v["name"], "view", schema=schema, table=v["name"]))
            if data["routines"]:
                cat = _make_item(f"例程 ({len(data['routines'])})", "category")
                children.append(cat)
                for r in data["routines"]:
                    cat.addChild(_make_item(f"{r['type'].lower()} {r['name']}", "routine",
                                            schema=schema, routine=r["name"]))
            if data["triggers"]:
                cat = _make_item(f"触发器 ({len(data['triggers'])})", "category")
                children.append(cat)
                for tr in data["triggers"]:
                    cat.addChild(_make_item(
                        f"{tr['name']} [{tr['event']} ON {tr['table']}]", "trigger",
                        schema=schema))
            _replace_children(item, children)
            item.setToolTip(0, f"{len(tables)} 表 / {len(views)} 视图 / {len(data['routines'])} 例程")

        run_async(fetch, done, lambda err: self._show_error(item, f"读取失败：{err}"))

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
                leaf = _make_item(f"{c['name']}  {c['data_type']}", "column")
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

    # ---- 交互 ----
    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        info = _info(item)
        kind = info.get(KIND_KEY)
        if kind == "profile":
            item.setExpanded(not item.isExpanded())
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
        action_er = None

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
        if kind == "database":
            action_er = menu.addAction("查看 ER 图…")

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
        elif chosen is action_er:
            self._er_database(item)

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
