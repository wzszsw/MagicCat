"""M57 回归：消息窗默认隐藏（对齐 Navicat），有消息才显示；消除初始黑色区。"""

from __future__ import annotations


def test_result_panel_hidden_then_shows(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    assert win._current_query_ws() is None, "初始只应显示对象页，不应预建查询标签"
    workspace = win._new_editor()
    assert workspace.result_panel.isVisible() is False, "新查询初始应隐藏消息区"
    workspace.result_panel.append_message("---- 执行 · SELECT 1")
    assert workspace.result_panel.isVisible() is True, "有消息应自动显示"


def test_result_panel_uses_reasonable_height_and_theme(qtbot):
    """首次出现时消息区只占查询区底部一段，并跟随应用主题。"""
    from PySide6.QtWidgets import QSplitter

    from magiccat.ui.editor import SqlEditorWidget
    from magiccat.ui.query_workspace import QueryWorkspace

    workspace = QueryWorkspace(SqlEditorWidget())
    qtbot.addWidget(workspace)
    workspace.resize(1280, 820)
    workspace.show()
    splitter = workspace.findChild(QSplitter)
    assert splitter is not None

    workspace.result_panel.append_message("---- 执行 · SELECT 1")
    qtbot.waitUntil(
        lambda: splitter.sizes()[1] > 0 and splitter.sizes()[1] < splitter.height() * 0.5,
        timeout=1000,
    )
    assert workspace.result_panel._log.styleSheet() == ""
