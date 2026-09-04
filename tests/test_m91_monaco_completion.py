"""Monaco SQL 上下文补全的 JS 逻辑回归。"""

from __future__ import annotations

import re


def _completion_function() -> str:
    from magiccat.ui.monaco_editor import _HTML_SOURCE

    match = re.search(r"function __completionFor\(text, data\) \{.*?\n\}",
                      _HTML_SOURCE, re.DOTALL)
    assert match
    return match.group(0)


def test_monaco_completion_supports_from_prefix_and_table_columns() -> None:
    from magiccat.ui.monaco_editor import _HTML_SOURCE

    source = _HTML_SOURCE

    assert "TABLE_CTX" in source
    assert "FROM|JOIN|INTO|UPDATE|TABLE|REFERENCES" in source
    assert "tablePrefix" in source
    assert "aliasMatch" in source
    assert "beforeDot" in source
    assert "cursorText.replace" in source
    assert "__completionProvider" in source


def test_mainwindow_completion_uses_pg_database_schema_api() -> None:
    import inspect

    from magiccat.ui.main_window import MainWindow

    source = inspect.getsource(MainWindow._update_completion_words)
    assert "schema_tables_in_database" in source
    assert "schema_columns_in_database" in source
