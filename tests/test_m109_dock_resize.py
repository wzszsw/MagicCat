"""M109 回归：非最大化窗口下左右 dock 与中央工作区可自由调宽。"""

from __future__ import annotations


def test_main_regions_allow_horizontal_dock_resize(qtbot, connection_service):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDockWidget, QSizePolicy

    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    qtbot.wait(20)

    docks = {dock.objectName(): dock for dock in window.findChildren(QDockWidget)}
    assert {"explorer_dock", "info_dock"} <= docks.keys()
    assert window.centralWidget().minimumWidth() == 0
    assert window.centralWidget().sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert window.editor_tabs.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored

    left = docks["explorer_dock"]
    before = left.width()
    window.resizeDocks([left], [before + 80], Qt.Horizontal)
    qtbot.wait(20)
    assert left.width() > before
