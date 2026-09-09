"""数据库集成测试的 Testcontainers 运行时适配。

该模块不导入具体容器实现，确保先探测 Docker/Podman API 并完成 Podman
兼容配置，再加载 testcontainers。产品测试仍使用 JDBC；容器只负责数据库
生命周期和随机宿主端口。
"""

from __future__ import annotations

import os
import platform
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from docker.errors import DockerException
from requests.exceptions import RequestException

FALSE_VALUES = frozenset({"0", "false", "no", "off"})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
CONTAINER_API_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class DatabaseSpec:
    """一种集成测试数据库的外部连接与容器约定。"""

    host_env: str
    port_env: str
    user_env: str
    password_env: str
    database_env: str | None
    default_host: str
    default_port: int
    default_user: str
    default_password: str
    default_database: str
    image_env: str
    default_image: str
    container_user: str
    container_password: str
    container_database: str
    container_port: int

    @property
    def external_env_names(self) -> tuple[str, ...]:
        names = (
            self.host_env,
            self.port_env,
            self.user_env,
            self.password_env,
        )
        return names + ((self.database_env,) if self.database_env else ())


DATABASE_SPECS: dict[str, DatabaseSpec] = {
    "mysql": DatabaseSpec(
        host_env="MAGICCAT_TEST_HOST",
        port_env="MAGICCAT_TEST_PORT",
        user_env="MAGICCAT_TEST_USER",
        password_env="MAGICCAT_TEST_PASSWORD",
        database_env=None,
        default_host="127.0.0.1",
        default_port=3306,
        default_user="root",
        default_password="",
        default_database="test",
        image_env="MAGICCAT_TEST_MYSQL_IMAGE",
        default_image="docker.io/library/mysql:8.4",
        container_user="root",
        container_password="magiccat_test_root",
        container_database="test",
        container_port=3306,
    ),
    "postgresql": DatabaseSpec(
        host_env="MAGICCAT_TEST_PG_HOST",
        port_env="MAGICCAT_TEST_PG_PORT",
        user_env="MAGICCAT_TEST_PG_USER",
        password_env="MAGICCAT_TEST_PG_PASSWORD",
        database_env="MAGICCAT_TEST_PG_DATABASE",
        default_host="127.0.0.1",
        default_port=5432,
        default_user="postgres",
        default_password="123456",
        default_database="postgres",
        image_env="MAGICCAT_TEST_POSTGRES_IMAGE",
        default_image="docker.io/library/postgres:16-alpine",
        container_user="postgres",
        container_password="magiccat_test_postgres",
        container_database="postgres",
        container_port=5432,
    ),
}


@dataclass(frozen=True)
class DatabaseEndpoint:
    """JDBC 集成测试使用的实际宿主连接参数。"""

    host: str
    port: int
    user: str
    password: str
    database: str

    def fixture_dict(self) -> dict[str, str | int]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
        }


@dataclass(frozen=True)
class ContainerRuntimeInfo:
    """已通过 API 预检的容器运行时。"""

    engine: str
    version: str
    docker_host: str
    is_podman: bool


class ContainerRuntimeUnavailable(RuntimeError):
    """Docker/Podman API 不可用；依赖容器的用例应跳过。"""


class _DockerClient(Protocol):
    def ping(self) -> bool: ...

    def version(self) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


def external_database_endpoint(
    database: str,
    environ: Mapping[str, str] | None = None,
) -> DatabaseEndpoint | None:
    """解析显式外部数据库配置；未配置时返回 ``None`` 以启用容器。"""

    values = os.environ if environ is None else environ
    spec = DATABASE_SPECS[database]
    if not any(name in values for name in spec.external_env_names):
        return None

    port_text = values.get(spec.port_env, str(spec.default_port))
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError(f"{spec.port_env} 必须是有效端口，当前值为 {port_text!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{spec.port_env} 必须在 1..65535，当前值为 {port}")

    return DatabaseEndpoint(
        host=values.get(spec.host_env, spec.default_host),
        port=port,
        user=values.get(spec.user_env, spec.default_user),
        password=values.get(spec.password_env, spec.default_password),
        database=(
            values.get(spec.database_env, spec.default_database)
            if spec.database_env
            else spec.default_database
        ),
    )


def container_tests_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """返回是否启用容器测试，并拒绝含糊的开关值。"""

    values = os.environ if environ is None else environ
    raw = values.get("MAGICCAT_TESTCONTAINERS", "1").strip().lower()
    if raw in TRUE_VALUES:
        return True
    if raw in FALSE_VALUES:
        return False
    raise ValueError(
        "MAGICCAT_TESTCONTAINERS 仅接受 1/0、true/false、yes/no 或 on/off，"
        f"当前值为 {raw!r}"
    )


def _default_client_factory() -> _DockerClient:
    from testcontainers.core.docker_client import DockerClient

    # 与真正启动容器时使用同一个 host 解析和客户端构造路径。
    return DockerClient(timeout=5).client


def _default_host_resolver() -> str | None:
    from testcontainers.core.docker_client import get_docker_host

    return get_docker_host()


def _unix_podman_hosts(environ: Mapping[str, str]) -> list[str]:
    candidates: list[Path] = []
    if runtime_dir := environ.get("XDG_RUNTIME_DIR"):
        candidates.append(Path(runtime_dir) / "podman" / "podman.sock")
    if hasattr(os, "getuid"):
        candidates.append(Path("/run/user") / str(os.getuid()) / "podman" / "podman.sock")
    candidates.append(Path("/run/podman/podman.sock"))
    return [f"unix://{path}" for path in candidates if path.exists()]


def _runtime_candidates(
    environ: Mapping[str, str],
    system_name: str,
    configured_host: str | None,
) -> list[tuple[str, str | None]]:
    # 显式 DOCKER_HOST 是用户选择，失败时不得悄悄改接其它引擎。
    if "DOCKER_HOST" in environ:
        return [("DOCKER_HOST", None)]
    # 包括 ~/.testcontainers.properties 的 tc.host 和非 default Docker context。
    if configured_host:
        return [("Testcontainers 配置接口", None)]

    candidates: list[tuple[str, str | None]] = [("Docker SDK 默认接口", None)]
    for alias in ("CONTAINER_HOST", "PODMAN_HOST"):
        if value := environ.get(alias):
            candidates.append((alias, value))

    if system_name == "Windows":
        machine = environ.get("PODMAN_MACHINE_NAME", "podman-machine-default")
        candidates.append((f"Podman machine {machine}", f"npipe:////./pipe/{machine}"))
    else:
        candidates.extend(("Podman socket", host) for host in _unix_podman_hosts(environ))

    unique: list[tuple[str, str | None]] = []
    seen: set[str | None] = set()
    for candidate in candidates:
        if candidate[1] not in seen:
            seen.add(candidate[1])
            unique.append(candidate)
    return unique


def _is_podman(version_info: Mapping[str, Any]) -> bool:
    components = version_info.get("Components", [])
    if isinstance(components, list):
        for component in components:
            if isinstance(component, Mapping) and "podman" in str(component.get("Name", "")).lower():
                return True
    return "podman" in str(version_info.get("Platform", "")).lower()


def _configure_podman(environ: MutableMapping[str, str]) -> None:
    # Podman remote socket 无法被 Ryuk 容器可靠挂载；session fixture 会显式清理。
    environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"
    if environ is os.environ:
        from testcontainers.core.config import testcontainers_config

        # 配置对象可能已在 host 解析时创建，显式同步其惰性属性缓存。
        testcontainers_config.ryuk_disabled = True


def ensure_container_runtime(
    environ: MutableMapping[str, str] | None = None,
    *,
    client_factory: Callable[[], _DockerClient] = _default_client_factory,
    host_resolver: Callable[[], str | None] = _default_host_resolver,
    system_name: str | None = None,
) -> ContainerRuntimeInfo:
    """预检 Docker API，默认接口失败后在本机约定位置寻找 Podman。"""

    values = os.environ if environ is None else environ
    if not container_tests_enabled(values):
        raise ContainerRuntimeUnavailable("MAGICCAT_TESTCONTAINERS 已关闭")

    configured_host = host_resolver()
    original_host_present = "DOCKER_HOST" in values
    original_host = values.get("DOCKER_HOST")
    errors: list[str] = []
    candidates = _runtime_candidates(values, system_name or platform.system(), configured_host)
    for label, candidate_host in candidates:
        if candidate_host is None:
            if not original_host_present:
                values.pop("DOCKER_HOST", None)
        else:
            values["DOCKER_HOST"] = candidate_host

        client: _DockerClient | None = None
        try:
            client = client_factory()
            if not client.ping():
                raise ConnectionError("API ping 返回 false")
            version_info = client.version()
            podman = _is_podman(version_info)
            if podman:
                _configure_podman(values)
            return ContainerRuntimeInfo(
                engine="Podman" if podman else "Docker",
                version=str(version_info.get("Version", "unknown")),
                docker_host=values.get("DOCKER_HOST") or configured_host or "default",
                is_podman=podman,
            )
        except (DockerException, RequestException, OSError) as exc:
            detail = " ".join(str(exc).split())
            errors.append(f"{label}: {type(exc).__name__}: {detail}")
        finally:
            if client is not None:
                with suppress(Exception):
                    client.close()

    if original_host_present:
        assert original_host is not None
        values["DOCKER_HOST"] = original_host
    else:
        values.pop("DOCKER_HOST", None)
    raise ContainerRuntimeUnavailable("；".join(errors) or "未找到 Docker/Podman API")


def create_database_container(
    database: str,
    environ: Mapping[str, str] | None = None,
    *,
    container_class: type[Any] | None = None,
) -> Any:
    """创建已配置但尚未启动的数据库容器。"""

    values = os.environ if environ is None else environ
    spec = DATABASE_SPECS[database]
    image = values.get(spec.image_env, spec.default_image)
    if database == "mysql":
        if container_class is None:
            from testcontainers.community.mysql import MySqlContainer

            container_class = MySqlContainer
        container = container_class(
            image=image,
            username=spec.container_user,
            root_password=spec.container_password,
            password=spec.container_password,
            dbname=spec.container_database,
            docker_client_kw={"timeout": CONTAINER_API_TIMEOUT_SECONDS},
        )
        return container.with_env("MYSQL_ROOT_HOST", "%")

    if database != "postgresql":
        raise ValueError(f"尚未实现 {database!r} 的测试容器工厂")
    if container_class is None:
        from testcontainers.community.postgres import PostgresContainer

        container_class = PostgresContainer
    return container_class(
        image=image,
        username=spec.container_user,
        password=spec.container_password,
        dbname=spec.container_database,
        driver=None,
        docker_client_kw={"timeout": CONTAINER_API_TIMEOUT_SECONDS},
    )


@contextmanager
def running_database_container(database: str, container: Any) -> Iterator[DatabaseEndpoint]:
    """启动并最终删除容器；启动失败也尽力清理半成品。"""

    spec = DATABASE_SPECS[database]
    try:
        container.start()
    except BaseException:
        with suppress(Exception):
            container.stop()
        raise

    try:
        yield DatabaseEndpoint(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(spec.container_port)),
            user=spec.container_user,
            password=spec.container_password,
            database=spec.container_database,
        )
    finally:
        container.stop()
