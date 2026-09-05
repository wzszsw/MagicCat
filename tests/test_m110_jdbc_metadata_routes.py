"""M110 回归：基础元数据入口统一路由到 JDBC DatabaseMetaData。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_metadata_api_routes_basic_objects_to_jdbc_standard_layer() -> None:
    source = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
              "magiccat" / "bridge" / "MetadataApi.java").read_text(encoding="utf-8")

    assert "return JdbcStandardMetadata.databases(configId);" in source
    assert "FROM pg_database" in source
    assert "return JdbcStandardMetadata.schemas(configId, database);" in source
    assert "return JdbcStandardMetadata.tables(configId, schema);" in source
    assert "return JdbcStandardMetadata.tables(configId, database, schema);" in source
    assert "return JdbcStandardMetadata.columns(configId, schema, null, table);" in source
    assert "return JdbcStandardMetadata.schemaColumns(configId, database, schema);" in source


def test_jdbc_standard_layer_supports_tables_views_and_column_shapes() -> None:
    source = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
              "magiccat" / "bridge" / "JdbcStandardMetadata.java").read_text(encoding="utf-8")

    assert "md.getCatalogs()" in source
    assert "conn.setCatalog(null);" not in source
    assert "schema 永远为 null" in source
    registry = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
                "magiccat" / "bridge" / "ConnectionRegistry.java").read_text(encoding="utf-8")
    assert "conn.setCatalog(database.trim())" in registry
    start = registry.index("static Connection connectionTo")
    end = registry.index("    /** 当前打开的配置", start)
    assert "conn.setSchema" not in registry[start:end]
    assert "md.getSchemas(useCatalog, \"%\")" in source
    assert "md.getTables(useCatalog, useSchema, \"%\"" in source
    assert '"SYSTEM TABLE"' in source
    assert "md.getColumns(useCatalog, useSchema, \"%\", \"%\")" in source
    assert "addTables(md, null, useCatalog, byName)" not in source
    assert '"MATERIALIZED VIEW"' in source


def test_jdbc_standard_layer_accepts_mysql_nullable_text_values() -> None:
    source = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
              "magiccat" / "bridge" / "JdbcStandardMetadata.java").read_text(encoding="utf-8")

    assert 'rs.getInt("NULLABLE")' not in source
    assert 'rs.getInt("IS_AUTOINCREMENT")' not in source
    assert source.count("nullableFlag(rs)") == 2
    assert '"YES".equalsIgnoreCase(value)' in source
    assert "Integer.parseInt(value)" in source
    assert "autoIncrementFlag(rs)" in source


def test_gaussdb_sequences_use_one_batch_sql_for_all_fields() -> None:
    api = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
           "magiccat" / "bridge" / "MetadataApi.java").read_text(encoding="utf-8")
    standard = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
                "magiccat" / "bridge" / "JdbcStandardMetadata.java").read_text(
                    encoding="utf-8"
                )

    assert "return JdbcStandardMetadata.gaussSequences(configId, database, schema);" in api
    start = standard.index("public static String gaussSequences")
    end = standard.index("    private static void addTables", start)
    body = standard[start:end]
    assert "information_schema.sequences" in body
    assert "pg_sequence_last_value(c.oid)" in body
    assert "pg_sequence_all_parameters" not in body
    assert "CROSS JOIN" not in body
    assert "LATERAL" not in body
    assert "md.getTables" not in body
    assert body.count("prepareStatement(") == 1


def test_pg_and_gaussdb_urls_do_not_receive_mysql_timeout_parameters() -> None:
    facade = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
              "magiccat" / "bridge" / "Facade.java").read_text(encoding="utf-8")

    assert 'return "jdbc:postgresql://" + host + ":" + port + "/" + db;' in facade
    assert 'return "jdbc:gaussdb://" + host + ":" + port + "/" + db;' in facade


def test_pgsql_key_routes_to_postgresql_in_java_bridge() -> None:
    registry = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
                "magiccat" / "bridge" / "ConnectionRegistry.java").read_text(
                    encoding="utf-8"
                )
    facade = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
              "magiccat" / "bridge" / "Facade.java").read_text(encoding="utf-8")

    assert 'open(configId, "MYSQL", host, port, database, user, password, "")' in registry
    assert '"PGSQL".equalsIgnoreCase(p.flavor())' in registry
    assert 'if ("pgsql".equals(f))' in facade
