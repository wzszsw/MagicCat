"""M76 测试：同一对象只开一个标签（Navicat 设定）——重开定位到已开标签，不新建。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services.query_library import QueryLibrary


def test_saved_query_singleton_tab(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="M76", group=DEFAULT_GROUP,
                                host="127.0.0.1", port=3306, username="root", password="")
    connection_service.add(profile)
    QueryLibrary.default().save(profile.id, "q_single", "SELECT 1;", schema="test")

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()

    # 第一次打开：新建标签
    win._open_saved_query(profile.id, "q_single")
    ed1 = win._active_editor()
    assert ed1.toPlainText().strip() == "SELECT 1;"
    n_after_first = win.editor_tabs.count()

    # 第二次打开：应定位到已有标签，不新建
    win._open_saved_query(profile.id, "q_single")
    ed2 = win._active_editor()
    assert ed1 is ed2, "同查询应复用同一标签"
    assert win.editor_tabs.count() == n_after_first, "不应新建标签"

    connection_service.close(profile.id)


def test_object_tab_mixed_dedup(qtbot, connection_service):
    """不同对象不同标签，同对象单例。"""
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="M76b", group=DEFAULT_GROUP,
                                host="127.0.0.1", port=3306, username="root", password="")
    connection_service.add(profile)
    QueryLibrary.default().save(profile.id, "q1", "SELECT 1;", schema="test")
    QueryLibrary.default().save(profile.id, "q2", "SELECT 2;", schema="test")

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()

    base = win.editor_tabs.count()  # 含构造时自动创建的查询标签
    win._open_saved_query(profile.id, "q1")
    win._open_saved_query(profile.id, "q2")
    n = win.editor_tabs.count()
    assert n == base + 2, "两个不同对象应新增两个标签"

    win._open_saved_query(profile.id, "q1")
    assert win.editor_tabs.count() == n, "重开 q1 不新建"

    connection_service.close(profile.id)
