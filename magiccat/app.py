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
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        from magiccat.services.profile_store import ProfileStore
        from magiccat.utils.logging_setup import configure_logging

        configure_logging(ProfileStore.default().root)
        return _selftest()

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
        _emit_selftest_result({"ok": True, "mysql": version, "select": row,
                               "jre_bundled": bundled_jre() is not None})
        return 0
    except Exception as exc:  # noqa: BLE001 —— 自检需汇报任意失败
        from magiccat.utils.errors import log_exception

        log_exception(logging.getLogger(__name__), "打包自检失败", exc)
        _emit_selftest_result({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1


def _emit_selftest_result(result: dict[str, object]) -> None:
    """输出自检结果；windowed 冻结程序没有 stdout 时改写入指定文件。"""
    text = json.dumps(result, ensure_ascii=False)
    output_path = os.environ.get("MAGICCAT_SELFTEST_OUTPUT")
    if output_path:
        Path(output_path).write_text(text + "\n", encoding="utf-8")
    if sys.stdout is not None:
        print(text)
