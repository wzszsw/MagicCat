"""M40 测试：自有矢量图标（函数/过程相异，常见类型齐全）。"""

from __future__ import annotations

from magiccat.ui.icons import icon


def test_icons_generated_for_kinds(qtbot):  # qtbot 确保 QApplication（QPixmap 需要）
    for kind in ("function", "procedure", "database", "table", "view", "trigger",
                 "saved_query", "query_folder", "group", "profile"):
        assert not icon(kind).isNull(), f"缺图标: {kind}"
    # 未知类型 → 空图标（Qt 默认）
    assert icon("not_exist").isNull()


def test_function_vs_procedure_distinct():
    fn, pr = icon("function"), icon("procedure")
    assert not fn.isNull() and not pr.isNull()
    assert fn.cacheKey() != pr.cacheKey(), "函数与存储过程应使用不同图标"


def test_routine_subtype_mapping():
    fn = icon("routine", "FUNCTION")
    pr = icon("routine", "PROCEDURE")
    assert not fn.isNull() and not pr.isNull()
    assert fn.cacheKey() != pr.cacheKey()
    assert not icon("routine").isNull()  # 无 subtype 时给默认函数图标
