"""M123 回归：长期会话保留连接池，一次性操作不创建短命连接池。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
REGISTRY = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
            "magiccat" / "bridge" / "ConnectionRegistry.java")
FACADE = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
          "magiccat" / "bridge" / "Facade.java")


def test_long_lived_pools_are_small_and_lazy() -> None:
    source = REGISTRY.read_text(encoding="utf-8")

    assert 'driverJar, 3, "mc-" + configId' in source
    assert "cfg.setMinimumIdle(maxPoolSize > 2 ? 1 : 0);" in source
    assert "cfg.setConnectionTimeout(10_000);" in source


def test_one_shot_cross_database_query_does_not_create_hikari_pool() -> None:
    source = REGISTRY.read_text(encoding="utf-8")
    start = source.index("public static String executeOnDatabase")
    end = source.index("    static HikariDataSource newDataSource", start)
    body = source[start:end]

    assert "directConnection(p, database)" in body
    assert "newDataSource(" not in body
    assert "HikariDataSource ds" not in body


def test_connection_test_does_not_replace_long_lived_pool() -> None:
    service = (ROOT / "magiccat" / "services" / "connection_service.py").read_text(
        encoding="utf-8"
    )
    start = service.index("    def test(self, profile: ConnectionProfile)")
    end = service.index("    @staticmethod", start)
    body = service[start:end]

    assert "Registry.test(" in body
    assert "Registry.open(" not in body
    assert "Registry.close(" not in body


def test_legacy_facade_uses_direct_jdbc_for_one_shot_calls() -> None:
    source = FACADE.read_text(encoding="utf-8")

    assert "import java.sql.DriverManager;" in source
    assert "HikariDataSource" not in source
    assert "DriverManager.getConnection" in source
