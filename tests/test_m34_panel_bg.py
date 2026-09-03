"""M34 回归：信息面板无黑色块（滚动区视口自填充 + 深色 QSS 覆盖）。"""

from __future__ import annotations

from magiccat.services.connection_service import ConnectionService


def test_panel_background_autofill(qtbot):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.connection_info_panel import ConnectionInfoPanel

    panel = ConnectionInfoPanel(ConnectionService(), MetadataService(ConnectionService()))
    qtbot.addWidget(panel)
    # 找到滚动区视口与内容体：都应开启自填充并使用窗口调色板（不再露黑底）
    from PySide6.QtWidgets import QScrollArea

    scroll = panel.findChild(QScrollArea)
    assert scroll is not None
    assert scroll.viewport().autoFillBackground() is True
    content = scroll.widget()
    assert content is not None and content.autoFillBackground() is True


def test_dark_qss_covers_scrollarea():
    from magiccat.ui.theme import DARK_QSS

    assert "QScrollArea" in DARK_QSS
    # 非空即可保证选择器已写入；黑块在两种主题下都不应出现
