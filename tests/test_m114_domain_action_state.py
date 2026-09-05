"""M114 回归：顶部功能域按钮与窗口级当前领域状态保持同步。"""

from __future__ import annotations


def test_domain_toolbar_has_exclusive_selected_state(qtbot, connection_service):
    from PySide6.QtGui import QAction

    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    assert window._current_domain == "tables"
    assert window._domain_actions["tables"].isChecked()
    assert sum(action.isChecked() for action in window._domain_actions.values()) == 1
    assert all(action.isCheckable() for action in window._domain_actions.values())
    assert not window._other_domain_button.isChecked()

    window._show_domain("views")
    assert window._current_domain == "views"
    assert window._domain_actions["views"].isChecked()
    assert not window._domain_actions["tables"].isChecked()
    assert sum(action.isChecked() for action in window._domain_actions.values()) == 1

    window._show_domain("sequences")
    assert window._current_domain == "sequences"
    assert not any(action.isChecked() for action in window._domain_actions.values())
    assert window._other_domain_button.isChecked()

    window._show_domain("tables")
    assert window._current_domain == "tables"
    assert window._domain_actions["tables"].isChecked()
    assert isinstance(window._domain_actions["tables"], QAction)


def test_tree_context_updates_object_tab_without_switching_query_tab(
    qtbot, connection_service, monkeypatch
):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.editor import SqlEditorWidget
    from magiccat.ui.main_window import MainWindow
    from magiccat.ui.query_workspace import QueryWorkspace

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)
    query = QueryWorkspace(SqlEditorWidget())
    index = window.editor_tabs.addTab(query, "查询")
    window.editor_tabs.setCurrentIndex(index)
    monkeypatch.setattr(window, "_set_current_profile", lambda _profile_id: None)
    calls: list[tuple[str, str, str, bool]] = []
    monkeypatch.setattr(
        window, "_show_domain",
        lambda domain, schema="", database="", activate=True:
            calls.append((domain, schema, database, activate)),
    )

    window._on_object_context_selected("profile-1", "db1", "public", "tables")

    assert window.editor_tabs.currentIndex() == index
    assert calls == [("tables", "public", "db1", False)]
