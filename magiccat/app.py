"""MagicCat 应用入口。

- 常规：启动 PySide6 主窗口；
- --selftest：无 GUI 自检（JVM 启动 + 本机 MySQL 联通 + JDBC 查询），
  用于验证打包产物（PyInstaller + 内嵌 jlink JRE）端到端可用。
"""

from __future__ import annotations

import json
import logging
import os
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        return _selftest()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from PySide6.QtWidgets import QApplication

    from magiccat.services.connection_service import ConnectionService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.profile_store import ProfileStore
    from magiccat.ui.main_window import MainWindow

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


def _selftest() -> int:
    """打包自检：不依赖 GUI/显示，验证 内嵌JVM + JDBC jar 全链路。"""
    host = os.environ.get("MAGICCAT_TEST_HOST", "127.0.0.1")
    port = int(os.environ.get("MAGICCAT_TEST_PORT", "3306"))
    user = os.environ.get("MAGICCAT_TEST_USER", "root")
    password = os.environ.get("MAGICCAT_TEST_PASSWORD", "")
    try:
        from magiccat.bridge.jvm import BridgeRuntime, bundled_jre

        bridge = BridgeRuntime()
        bridge.start()
        Registry = bridge.jclass("com.magiccat.bridge.ConnectionRegistry")
        Registry.open("__selftest__", host, port, "", user, password)
        version = Registry.ping("__selftest__")
        raw = Registry.execute("__selftest__", "SELECT 1 + 1 AS two", 5)
        row = json.loads(raw)["rows"][0][0]
        Registry.close("__selftest__")
        bridge.shutdown()
        print(json.dumps({"ok": True, "mysql": version, "select": row,
                          "jre_bundled": bundled_jre() is not None}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 —— 自检需汇报任意失败
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False))
        return 1
