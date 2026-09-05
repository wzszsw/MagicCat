"""M136 回归：未保存查询使用“无标题”显示名和独立内部定位键。"""

from __future__ import annotations


def test_untitled_query_tabs_have_same_title_and_unique_keys(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    first = window._new_editor()
    second = window._new_editor()
    first_index = window.editor_tabs.indexOf(first)
    second_index = window.editor_tabs.indexOf(second)

    assert window.editor_tabs.tabText(first_index) == "无标题"
    assert window.editor_tabs.tabText(second_index) == "无标题"
    assert first.tab_key != second.tab_key
    assert first.tab_key.startswith("query:untitled:")
    assert second.tab_key.startswith("query:untitled:")
