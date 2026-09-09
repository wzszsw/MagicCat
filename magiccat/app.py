"""MagicCat 应用入口：启动 PySide6 主窗口。"""

from __future__ import annotations

import os
import sys


def main() -> int:
    # QtWebEngine 需要在 QApplication 前设置（无沙箱/禁 GPU，兼容无显示/offscreen 环境）
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--no-sandbox --disable-gpu --disable-software-rasterizer")
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

    from magiccat.services.profile_store import ProfileStore
    from magiccat.utils.logging_setup import configure_logging

    configure_logging(ProfileStore.default().root)

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from magiccat.resources import app_icon_png
    from magiccat.services.connection_service import ConnectionService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.profile_store import ProfileStore
    from magiccat.ui.main_window import MainWindow
    from magiccat.ui.startup_splash import StartupSplash

    app = QApplication(sys.argv)
    app.setApplicationName("MagicCat")
    app.setOrganizationName("MagicCat")
    app.setWindowIcon(QIcon(app_icon_png()))

    splash = StartupSplash()
    splash.show()
    app.processEvents()

    connections = ConnectionService(ProfileStore.default())
    metadata = MetadataService(connections)
    window = MainWindow(connections, metadata)

    def reveal_main_window() -> None:
        # 先同步隐藏 splash，再显示已经完成 WebEngine 初始化的主窗口，
        # 避免 Windows 合成时主窗口内容盖住 splash 的下半部分。
        splash.close()
        window.show()

    # 首个 QWebEngineView 初始化完成前不显示主窗口，避免 Windows 首帧白闪。
    window.prepare_for_show(reveal_main_window)

    rc = app.exec()
    connections.close_all()
    return rc
