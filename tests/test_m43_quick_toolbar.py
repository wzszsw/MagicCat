"""M43 测试：顶部快速访问栏（连接/新建查询/表/视图/函数）。"""

from __future__ import annotations


def test_quick_toolbar_actions(qtbot, connection_service):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QToolBar

    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    toolbar = win.findChild(QToolBar, "quick_toolbar")
    assert toolbar is not None, "缺少顶部快速访问栏"
    texts = [a.text() for a in toolbar.actions() if a.text()]
    for expected in ("新建连接", "新建查询", "表", "视图", "函数"):
        assert expected in texts, f"缺少动作: {expected}"
    for a in toolbar.actions():
        if a.text() in ("表", "视图", "函数"):
            assert not a.icon().isNull(), f"{a.text()} 无图标"
    # 样式：图标下方文字（Navicat 风格按钮条）
    assert toolbar.toolButtonStyle() == Qt.ToolButtonTextUnderIcon
    assert toolbar.iconSize().height() >= 24
