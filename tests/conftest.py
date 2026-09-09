"""pytest 全局配置。

- 所有 Qt 测试以 offscreen 平台运行（无显示环境下可执行）。
- 环境变量需在导入 PySide6 前设置。
- 数据库集成测试默认由 Testcontainers 按 session 启动，产品链路仍走 JDBC。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# QtWebEngine 需在 QApplication 前设置无沙箱/禁 GPU
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --disable-software-rasterizer")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
# 测试用自研编辑器（同步文本、无 WebEngine 崩溃）；monaco 用于真实应用
os.environ.setdefault("MAGICCAT_EDITOR", "plain")

import pytest
from db_test_runtime import (
    ContainerRuntimeInfo,
    ContainerRuntimeUnavailable,
    create_database_container,
    ensure_container_runtime,
    external_database_endpoint,
    running_database_container,
)


@pytest.fixture(scope="session")
def _container_runtime() -> ContainerRuntimeInfo | ContainerRuntimeUnavailable:
    """只做容器 API 预检；API 不可用由具体数据库 fixture 转为 skip。"""

    try:
        return ensure_container_runtime()
    except ContainerRuntimeUnavailable as exc:
        return exc


def _require_container_runtime(request: pytest.FixtureRequest) -> ContainerRuntimeInfo:
    runtime = request.getfixturevalue("_container_runtime")
    if isinstance(runtime, ContainerRuntimeUnavailable):
        pytest.skip(f"容器环境不可用，跳过数据库集成用例：{runtime}")
    return runtime


@pytest.fixture(scope="session")
def _mysql_session_env(request: pytest.FixtureRequest) -> Iterator[dict[str, str | int]]:
    external = external_database_endpoint("mysql")
    if external is not None:
        yield external.fixture_dict()
        return

    _require_container_runtime(request)
    container = create_database_container("mysql")
    with running_database_container("mysql", container) as endpoint:
        yield endpoint.fixture_dict()


@pytest.fixture(scope="session")
def _pg_session_env(request: pytest.FixtureRequest) -> Iterator[dict[str, str | int]]:
    external = external_database_endpoint("postgresql")
    if external is not None:
        yield external.fixture_dict()
        return

    _require_container_runtime(request)
    container = create_database_container("postgresql")
    with running_database_container("postgresql", container) as endpoint:
        yield endpoint.fixture_dict()


@pytest.fixture()
def mysql_env(_mysql_session_env: dict[str, str | int]) -> dict[str, str | int]:
    """每个用例拿独立字典，底层 MySQL 容器在本次 pytest session 内复用。"""

    return dict(_mysql_session_env)


@pytest.fixture()
def pg_env(_pg_session_env: dict[str, str | int]) -> dict[str, str | int]:
    """每个用例拿独立字典，底层 PostgreSQL 容器在本次 pytest session 内复用。"""

    return dict(_pg_session_env)


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
