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


def test_mysql_catalog_schema_mapping_does_not_clear_catalog_with_null() -> None:
    source = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
              "magiccat" / "bridge" / "JdbcStandardMetadata.java").read_text(
                  encoding="utf-8"
              )

    start = source.index("public static String databases")
    end = source.index("    // ---- 模式列表", start)
    databases_body = source[start:end]
    assert "getCatalogs()" in databases_body
    assert "conn.setCatalog(null)" not in databases_body

    tables_start = source.index("public static String tables(String configId, String schema)")
    tables_end = source.index("     * GaussDB 序列", tables_start)
    tables_body = source[tables_start:tables_end]
    assert "return tables(configId, schema, \"\");" in tables_body
    assert "return tables(configId, \"\", schema);" in tables_body
    assert "addTables(md, null, useCatalog, byName)" not in tables_body


def test_mysql_metadata_context_sets_catalog_but_never_schema() -> None:
    source = REGISTRY.read_text(encoding="utf-8")
    start = source.index("static Connection connectionTo")
    end = source.index("    /** 当前打开的配置", start)
    body = source[start:end]

    assert "!isPostgres(configId)" in body
    assert "conn.setCatalog(database.trim())" in body
    assert "conn.setSchema" not in body
