"""M111 回归：启动时只显示对象页，查询标签由用户操作后创建。"""

from __future__ import annotations


def test_main_window_does_not_precreate_query_tab(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    assert window.editor_tabs.count() == 1
    assert window.editor_tabs.tabText(0) == "对象"
    assert window.domain_stack.currentWidget() is window.table_page
    assert window._current_query_ws() is None

    workspace = window._new_editor()
    assert window.editor_tabs.count() == 2
    assert window.editor_tabs.currentWidget() is workspace
