"""M57 回归：消息窗默认隐藏（对齐 Navicat），有消息才显示；消除初始黑色区。"""

from __future__ import annotations


def test_result_panel_hidden_then_shows(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    assert win.result_panel.isVisible() is False, "初始应隐藏（不应露黑色消息区）"
    win.result_panel.append_message("---- 执行 · SELECT 1")
    assert win.result_panel.isVisible() is True, "有消息应自动显示"
