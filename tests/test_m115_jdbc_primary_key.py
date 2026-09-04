"""M115 回归：表数据页主键读取统一使用 JDBC DatabaseMetaData。"""

from __future__ import annotations

from pathlib import Path


def test_table_data_primary_key_uses_jdbc_metadata() -> None:
    source = (Path(__file__).parents[1] / "java-bridge" / "src" / "main" /
              "java" / "com" / "magiccat" / "bridge" / "TableDataApi.java").read_text(
                  encoding="utf-8"
              )

    assert "DatabaseMetaData" in source
    assert "getPrimaryKeys(useCatalog, useSchema, table)" in source
    assert "array_position" not in source
    assert "KEY_SEQ" in source
