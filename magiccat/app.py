"""MagicCat 应用入口（M2：连接管理 + 对象浏览器）。"""

from __future__ import annotations

import logging
import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from magiccat.services.connection_service import ConnectionService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.profile_store import ProfileStore
    from magiccat.ui.main_window import MainWindow

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = QApplication(sys.argv)
    app.setApplicationName("MagicCat")
    app.setOrganizationName("MagicCat")

    connections = ConnectionService(ProfileStore.default())
    metadata = MetadataService(connections)
    window = MainWindow(connections, metadata)
    window.show()

    rc = app.exec()
    connections.close_all()
    return rc
