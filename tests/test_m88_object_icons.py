"""对象树 schema/table 图标不能相同。"""

from __future__ import annotations


def test_schema_and_table_icons_are_distinct(qtbot) -> None:
    from magiccat.ui.icons import icon

    schema = icon("schema")
    table = icon("table")
    assert not schema.isNull()
    assert not table.isNull()
    assert schema.cacheKey() != table.cacheKey()
