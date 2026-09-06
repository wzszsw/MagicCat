"""M32 测试：具名查询库（对标 Navicat “查询”抽象）。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services.query_library import QueryLibrary


def test_query_library_crud(tmp_path):
    from magiccat.storage.profile_store import JsonProfileStore

    JsonProfileStore(tmp_path).save_profile(ConnectionProfile(id="p1", name="p1"))
    lib = QueryLibrary(tmp_path)
    assert lib.list("p1") == []
    lib.save("p1", "查询A", "SELECT 1", schema="test")
    lib.save("p1", "查询A", "SELECT 2", schema="test")   # 同名覆盖
    lib.save("p1", "b", "SELECT 3", schema="")
    items = lib.list("p1")
    assert {i["name"] for i in items} == {"查询A", "b"}
    assert lib.get("p1", "查询A")["content"] == "SELECT 2"
    assert lib.get("p1", "b")["schema"] == ""
    assert lib.delete("p1", "b") is True
    assert lib.list("p1") == [{"name": "查询A", "database": "", "schema": "test",
                               "updated_at": lib.list("p1")[0]["updated_at"]}]


def test_query_folder_in_tree(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer

    profile = ConnectionProfile(name="M32", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    QueryLibrary.default().save(profile.id, "统计分析", "SELECT MAX(id) FROM t", database="test")

    explorer = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(explorer)
    explorer.load_profiles()
    item = explorer.profile_item(profile.id)
    item.setExpanded(True)

    def db_node() -> object | None:
        for i in range(item.childCount()):
            c = item.child(i)
            info = c.data(0, 0x0100) or {}
            if info.get("kind") == "database" and info.get("data", {}).get("schema") == "test":
                return c
        return None

    def has_query() -> bool:
        node = db_node()
        if node is None:
            return False
        if node.childCount() <= 1:  # 占位子项=1，先展开库（懒加载骨架）
            node.setExpanded(True)
            return False
        for i in range(node.childCount()):
            if node.child(i).text(0) != "查询":
                continue
            return any(node.child(i).child(j).text(0) == "统计分析"
                       for j in range(node.child(i).childCount()))
        return False

    qtbot.waitUntil(has_query, timeout=25_000)
    connection_service.close(profile.id)


def test_open_saved_query_in_editor(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="M32b", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    QueryLibrary.default().save(profile.id, "q_开库", "SELECT 42 AS answer;", database="test")

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    win._open_saved_query(profile.id, "q_开库")
    editor = win._active_editor()
    assert editor.toPlainText().strip() == "SELECT 42 AS answer;"
    assert win.editor_tabs.tabText(win.editor_tabs.indexOf(editor)) == "q_开库"
    connection_service.close(profile.id)


def test_open_saved_query_save_updates_without_name_dialog(qtbot, connection_service,
                                                            monkeypatch):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="M32save", group=DEFAULT_GROUP,
                                host="127.0.0.1", port=3306, username="root")
    connection_service.add(profile)
    library = QueryLibrary.default()
    library.save(profile.id, "已有查询", "SELECT 1;", database="test")

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    win._open_saved_query(profile.id, "已有查询")
    editor = win._active_editor()
    editor.setPlainText("SELECT 2;")

    def fail_dialog(*_args, **_kwargs):
        raise AssertionError("编辑已有查询不应再次要求输入名称")

    monkeypatch.setattr("magiccat.ui.main_window.QInputDialog.getText", fail_dialog)
    win._save_query_dialog()

    assert library.get(profile.id, "已有查询")["content"] == "SELECT 2;"
    connection_service.close(profile.id)


def test_query_tree_keeps_saved_queries_when_category_expands(qtbot, connection_service):
    from PySide6.QtWidgets import QTreeWidgetItem

    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui import object_explorer as oe
    from magiccat.ui.object_explorer import ObjectExplorer

    profile = ConnectionProfile(name="M32tree", group=DEFAULT_GROUP,
                                host="127.0.0.1", port=3306, username="root")
    connection_service.add(profile)
    QueryLibrary.default().save(profile.id, "树中查询", "SELECT 1", database="test")

    explorer = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(explorer)
    profile_item = QTreeWidgetItem([profile.name])
    profile_item.setData(0, oe.Qt.UserRole, {oe.KIND_KEY: "profile",
                                             oe.DATA_KEY: {"profile_id": profile.id}})
    explorer.addTopLevelItem(profile_item)
    database = oe._make_item("test", "database", schema="test")
    profile_item.addChild(database)
    category = oe._make_item("查询", "category", database="test", schema="test",
                             cat_type="queries")
    database.addChild(category)

    explorer._load_category(category)

    assert category.childCount() == 1
    assert category.child(0).text(0) == "树中查询"
    connection_service.close(profile.id)
