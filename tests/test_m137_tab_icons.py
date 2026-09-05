"""M137 回归：编辑器标签按内容类型显示 Navicat 风格图标。"""

from __future__ import annotations


def test_object_tab_icon_tracks_current_domain(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.icons import icon
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    expected = {
        "tables": "table",
        "views": "view",
        "routines": "function",
        "triggers": "trigger",
        "sequences": "sequence",
        "users": "user",
        "queries": "query",
    }
    for domain, kind in expected.items():
        window._set_domain_action(domain)
        assert window.editor_tabs.tabIcon(0).cacheKey() == icon(kind).cacheKey()


def test_editor_tabs_use_content_icons(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.icons import icon
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    query = window._new_editor()
    assert window.editor_tabs.tabIcon(window.editor_tabs.indexOf(query)).cacheKey() == \
        icon("query").cacheKey()

    cases = (
        ("view:p:s:v", "视图", "view"),
        ("routine:p:s:f", "函数", "function"),
        ("routine:p:s:p", "过程", "procedure"),
        ("trigger:p:s:t", "触发器", "trigger"),
    )
    for key, title, kind in cases:
        editor = window._open_object_tab(key, title, "SELECT 1;", icon_kind=kind)
        index = window.editor_tabs.indexOf(editor)
        assert window.editor_tabs.tabIcon(index).cacheKey() == icon(kind).cacheKey()


def test_table_data_tab_uses_table_icon(qtbot, connection_service, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui import data_table
    from magiccat.ui.icons import icon
    from magiccat.ui.main_window import MainWindow

    class StubDataTable(QWidget):
        def __init__(self, _profile, _database, _schema, table, *_args):
            super().__init__()
            self.tab_key = f"stub:{table}"

    monkeypatch.setattr(data_table, "DataTableWidget", StubDataTable)
    profile = ConnectionProfile(name="M137", group=DEFAULT_GROUP,
                                host="127.0.0.1", port=3306,
                                username="root", password="")
    connection_service.add(profile)
    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    window._on_open_table(profile.id, "app", "app", "books")
    index = window.editor_tabs.currentIndex()
    assert window.editor_tabs.tabIcon(index).cacheKey() == icon("table").cacheKey()
