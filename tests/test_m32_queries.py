"""M32 测试：具名查询库（对标 Navicat “查询”抽象）。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services.query_library import QueryLibrary


def test_query_library_crud(tmp_path):
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
    assert lib.list("p1") == [{"name": "查询A", "schema": "test",
                               "updated_at": lib.list("p1")[0]["updated_at"]}]


def test_query_folder_in_tree(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer

    profile = ConnectionProfile(name="M32", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    QueryLibrary.default().save(profile.id, "统计分析", "SELECT MAX(id) FROM t", schema="test")

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
    QueryLibrary.default().save(profile.id, "q_开库", "SELECT 42 AS answer;", schema="test")

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    win._open_saved_query(profile.id, "q_开库")
    editor = win._active_editor()
    assert editor.toPlainText().strip() == "SELECT 42 AS answer;"
    assert win.editor_tabs.tabText(win.editor_tabs.indexOf(editor)) == "q_开库"
    connection_service.close(profile.id)
