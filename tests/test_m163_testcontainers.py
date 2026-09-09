"""M163：Testcontainers 数据库测试运行时与 Podman 兼容约定。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from db_test_runtime import (
    ContainerRuntimeUnavailable,
    container_tests_enabled,
    create_database_container,
    ensure_container_runtime,
    external_database_endpoint,
    running_database_container,
)


class _FakeDockerClient:
    def __init__(self, version_info: Mapping[str, Any], *, ping: bool = True) -> None:
        self.version_info = version_info
        self.ping_result = ping
        self.closed = False

    def ping(self) -> bool:
        return self.ping_result

    def version(self) -> Mapping[str, Any]:
        return self.version_info

    def close(self) -> None:
        self.closed = True


class _FakeContainer:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.environment: dict[str, str] = {}
        self.started = 0
        self.stopped = 0

    def with_env(self, name: str, value: str) -> _FakeContainer:
        self.environment[name] = value
        return self

    def start(self) -> _FakeContainer:
        self.started += 1
        return self

    def stop(self) -> None:
        self.stopped += 1

    def get_container_host_ip(self) -> str:
        return "127.0.0.1"

    def get_exposed_port(self, port: int) -> str:
        return {3306: "49173", 5432: "49174"}[port]


def test_external_database_partial_override_preserves_legacy_defaults() -> None:
    endpoint = external_database_endpoint("mysql", {"MAGICCAT_TEST_PASSWORD": ""})

    assert endpoint is not None
    assert endpoint.fixture_dict() == {
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "test",
    }


def test_external_postgresql_config_and_invalid_port() -> None:
    endpoint = external_database_endpoint(
        "postgresql",
        {
            "MAGICCAT_TEST_PG_HOST": "db.internal",
            "MAGICCAT_TEST_PG_PORT": "15432",
            "MAGICCAT_TEST_PG_USER": "admin",
            "MAGICCAT_TEST_PG_PASSWORD": "secret",
            "MAGICCAT_TEST_PG_DATABASE": "postgres",
        },
    )

    assert endpoint is not None
    assert endpoint.host == "db.internal"
    assert endpoint.port == 15432
    assert endpoint.user == "admin"
    assert endpoint.password == "secret"
    with pytest.raises(ValueError, match="MAGICCAT_TEST_PG_PORT"):
        external_database_endpoint("postgresql", {"MAGICCAT_TEST_PG_PORT": "not-a-port"})


def test_no_external_config_selects_testcontainers() -> None:
    assert external_database_endpoint("mysql", {}) is None
    assert external_database_endpoint("postgresql", {}) is None
    assert external_database_endpoint("mysql", {"MAGICCAT_TEST_DATABASE": "ignored"}) is None


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_testcontainers_switch_can_disable_runtime(value: str) -> None:
    assert not container_tests_enabled({"MAGICCAT_TESTCONTAINERS": value})
    with pytest.raises(ContainerRuntimeUnavailable, match="已关闭"):
        ensure_container_runtime(
            {"MAGICCAT_TESTCONTAINERS": value},
            client_factory=lambda: pytest.fail("关闭时不应探测容器 API"),
        )


def test_invalid_testcontainers_switch_is_configuration_error() -> None:
    with pytest.raises(ValueError, match="MAGICCAT_TESTCONTAINERS"):
        container_tests_enabled({"MAGICCAT_TESTCONTAINERS": "perhaps"})


def test_runtime_respects_explicit_docker_host() -> None:
    environ = {"DOCKER_HOST": "tcp://container.example:2375"}
    client = _FakeDockerClient({"Version": "27.1", "Components": [{"Name": "Docker Engine"}]})

    info = ensure_container_runtime(
        environ,
        client_factory=lambda: client,
        host_resolver=lambda: "unix:///context/must-not-win.sock",
        system_name="Windows",
    )

    assert info.engine == "Docker"
    assert info.docker_host == "tcp://container.example:2375"
    assert environ["DOCKER_HOST"] == "tcp://container.example:2375"
    assert "TESTCONTAINERS_RYUK_DISABLED" not in environ
    assert client.closed


def test_windows_default_failure_falls_back_to_podman_pipe() -> None:
    environ = {"TESTCONTAINERS_RYUK_DISABLED": "false"}
    attempted_hosts: list[str | None] = []

    def factory() -> _FakeDockerClient:
        attempted_hosts.append(environ.get("DOCKER_HOST"))
        if len(attempted_hosts) == 1:
            raise OSError("default pipe unavailable")
        return _FakeDockerClient(
            {"Version": "5.8.1", "Components": [{"Name": "Podman Engine"}]}
        )

    info = ensure_container_runtime(
        environ,
        client_factory=factory,
        host_resolver=lambda: None,
        system_name="Windows",
    )

    assert attempted_hosts == [None, "npipe:////./pipe/podman-machine-default"]
    assert info.engine == "Podman"
    assert info.is_podman
    assert environ["DOCKER_HOST"] == "npipe:////./pipe/podman-machine-default"
    assert environ["TESTCONTAINERS_RYUK_DISABLED"] == "true"


def test_unavailable_runtime_restores_implicit_docker_host() -> None:
    environ: dict[str, str] = {}

    with pytest.raises(ContainerRuntimeUnavailable, match="Docker SDK 默认接口"):
        ensure_container_runtime(
            environ,
            client_factory=lambda: (_ for _ in ()).throw(OSError("engine stopped")),
            host_resolver=lambda: None,
            system_name="Linux",
        )

    assert "DOCKER_HOST" not in environ


def test_testcontainers_configured_host_is_probed_without_fallback() -> None:
    environ: dict[str, str] = {}
    calls = 0

    def factory() -> _FakeDockerClient:
        nonlocal calls
        calls += 1
        return _FakeDockerClient({"Version": "27.1", "Components": [{"Name": "Docker Engine"}]})

    info = ensure_container_runtime(
        environ,
        client_factory=factory,
        host_resolver=lambda: "unix:///tmp/docker-context.sock",
        system_name="Windows",
    )

    assert calls == 1
    assert info.docker_host == "unix:///tmp/docker-context.sock"
    assert "DOCKER_HOST" not in environ


def test_unexpected_runtime_programming_error_is_not_a_skip() -> None:
    with pytest.raises(TypeError, match="broken client factory"):
        ensure_container_runtime(
            {},
            client_factory=lambda: (_ for _ in ()).throw(TypeError("broken client factory")),
            host_resolver=lambda: None,
            system_name="Windows",
        )


def test_mysql_container_uses_pinned_image_root_and_global_privileges() -> None:
    container = create_database_container("mysql", {}, container_class=_FakeContainer)

    assert container.kwargs == {
        "image": "docker.io/library/mysql:8.4",
        "username": "root",
        "root_password": "magiccat_test_root",
        "password": "magiccat_test_root",
        "dbname": "test",
        "docker_client_kw": {"timeout": 300},
    }
    assert container.environment == {"MYSQL_ROOT_HOST": "%"}


def test_postgresql_container_uses_pinned_image_and_superuser() -> None:
    container = create_database_container(
        "postgresql",
        {"MAGICCAT_TEST_POSTGRES_IMAGE": "registry.local/postgres:test"},
        container_class=_FakeContainer,
    )

    assert container.kwargs == {
        "image": "registry.local/postgres:test",
        "username": "postgres",
        "password": "magiccat_test_postgres",
        "dbname": "postgres",
        "driver": None,
        "docker_client_kw": {"timeout": 300},
    }


@pytest.mark.parametrize(
    ("database", "expected_port"),
    [("mysql", 49173), ("postgresql", 49174)],
)
def test_container_lifecycle_returns_random_port_and_cleans_up(
    database: str,
    expected_port: int,
) -> None:
    container = _FakeContainer()

    with running_database_container(database, container) as endpoint:
        assert endpoint.host == "127.0.0.1"
        assert endpoint.port == expected_port
        assert container.started == 1
        assert container.stopped == 0

    assert container.stopped == 1


def test_container_start_failure_is_not_treated_as_runtime_skip() -> None:
    class _BrokenContainer(_FakeContainer):
        def start(self) -> _FakeContainer:
            self.started += 1
            raise RuntimeError("database readiness failed")

    container = _BrokenContainer()
    with (
        pytest.raises(RuntimeError, match="database readiness failed"),
        running_database_container("mysql", container),
    ):
        pytest.fail("启动失败时不应进入测试")

    assert container.stopped == 1
