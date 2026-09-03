"""M21 测试：Java 错误文案清理。"""

from __future__ import annotations

from magiccat.utils.errors import clean_java_error, format_exc


class _FakeExc(Exception):
    pass


def test_clean_double_prefix():
    raw = ("java.lang.IllegalStateException: java.lang.IllegalStateException: "
           "查询失败: Unknown column 'x' in 'field list'")
    assert clean_java_error(raw) == "查询失败: Unknown column 'x' in 'field list'"


def test_clean_single_prefix():
    assert clean_java_error("java.sql.SQLException: Access denied") == "Access denied"


def test_format_exc_no_java_class():
    exc = _FakeExc("java.lang.IllegalStateException: java.lang.IllegalStateException: 已取消")
    text = format_exc(exc)
    assert text == "_FakeExc: 已取消"
    assert "java.lang" not in text
