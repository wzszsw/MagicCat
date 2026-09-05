"""pytest 全局配置。

- 所有 Qt 测试以 offscreen 平台运行（无显示环境下可执行）。
- 环境变量需在导入 PySide6 前设置。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# QtWebEngine 需在 QApplication 前设置无沙箱/禁 GPU
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --disable-software-rasterizer")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
# 测试用自研编辑器（同步文本、无 WebEngine 崩溃）；monaco 用于真实应用
os.environ.setdefault("MAGICCAT_EDITOR", "plain")

import pytest

HOST = os.environ.get("MAGICCAT_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAGICCAT_TEST_PORT", "3306"))
USER = os.environ.get("MAGICCAT_TEST_USER", "root")
PASSWORD = os.environ.get("MAGICCAT_TEST_PASSWORD", "")


def _mysql_reachable() -> bool:
    import socket

    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            return True
    except OSError:
        return False


PG_HOST = os.environ.get("MAGICCAT_TEST_PG_HOST", "127.0.0.1")
PG_PORT = int(os.environ.get("MAGICCAT_TEST_PG_PORT", "5432"))
PG_USER = os.environ.get("MAGICCAT_TEST_PG_USER", "postgres")
PG_PASSWORD = os.environ.get("MAGICCAT_TEST_PG_PASSWORD", "123456")


def _pg_reachable() -> bool:
    import socket

    try:
        with socket.create_connection((PG_HOST, PG_PORT), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture()
def mysql_env() -> dict:
    if not _mysql_reachable():
        pytest.skip(f"本机 MySQL {HOST}:{PORT} 不可达，跳过集成用例")
    return {"host": HOST, "port": PORT, "user": USER, "password": PASSWORD}


@pytest.fixture()
def pg_env() -> dict:
    if not _pg_reachable():
        pytest.skip(f"本机 PostgreSQL {PG_HOST}:{PG_PORT} 不可达，跳过集成用例")
    return {"host": PG_HOST, "port": PG_PORT, "user": PG_USER, "password": PG_PASSWORD}


@pytest.fixture()
def profile_store(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGICCAT_HOME", str(tmp_path))
    from magiccat.services.profile_store import ProfileStore

    store = ProfileStore(tmp_path)
    yield store


@pytest.fixture()
def connection_service(profile_store):
    from magiccat.services.connection_service import ConnectionService

    service = ConnectionService(profile_store)
    yield service
    service.close_all()
