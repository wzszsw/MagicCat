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
    assert "conn.setCatalog(null);" in source
    assert "md.getSchemas(useCatalog, \"%\")" in source
    assert "md.getTables(useCatalog, useSchema, \"%\"" in source
    assert "md.getColumns(useCatalog, useSchema, \"%\", \"%\")" in source
    assert '"MATERIALIZED VIEW"' in source


def test_gaussdb_sequences_use_jdbc_sequence_metadata_and_batch_details() -> None:
    api = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
           "magiccat" / "bridge" / "MetadataApi.java").read_text(encoding="utf-8")
    standard = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
                "magiccat" / "bridge" / "JdbcStandardMetadata.java").read_text(
                    encoding="utf-8"
                )

    assert "return JdbcStandardMetadata.gaussSequences(configId, database, schema);" in api
    assert "md.getTables(useCatalog, useSchema, \"%\",\n                                             new String[] {\"SEQUENCE\"})" in standard
    assert "pg_sequence_all_parameters" in standard


def test_pg_and_gaussdb_urls_do_not_receive_mysql_timeout_parameters() -> None:
    facade = (ROOT / "java-bridge" / "src" / "main" / "java" / "com" /
              "magiccat" / "bridge" / "Facade.java").read_text(encoding="utf-8")

    assert 'return "jdbc:postgresql://" + host + ":" + port + "/" + db;' in facade
    assert 'return "jdbc:gaussdb://" + host + ":" + port + "/" + db;' in facade
