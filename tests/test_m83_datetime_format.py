"""M83 测试：日期时间统一显示为 `YYYY-MM-DD HH:MM:SS`（本地时区）。"""

from __future__ import annotations


def test_format_datetime_iso_utc():
    from magiccat.utils.datetime_format import format_datetime

    # UTC ISO（带 +00:00）→ 转本地时区并去除 T/时区
    out = format_datetime("2026-09-04T10:55:08+00:00")
    assert "T" not in out and "+00:00" not in out
    assert " " in out and out.count(":") == 2


def test_format_datetime_already_formatted():
    from magiccat.utils.datetime_format import format_datetime

    assert format_datetime("2026-09-04 10:55:08") == "2026-09-04 10:55:08"


def test_format_datetime_ms_and_naive():
    from magiccat.utils.datetime_format import format_datetime

    # 带毫秒 → 去除
    assert format_datetime("2026-09-04 10:55:08.0") == "2026-09-04 10:55:08"
    # 无时区 ISO → 保留本地位
    assert format_datetime("2026-09-04T10:55:08") == "2026-09-04 10:55:08"


def test_format_datetime_non_date(): 
    from magiccat.utils.datetime_format import format_datetime

    assert format_datetime("abc") == "abc"
    assert format_datetime("") == ""
    assert format_datetime("hello") == "hello"


def test_object_browse_date_column(qtbot):
    from datetime import UTC, datetime

    from magiccat.ui.query_browse import QueryBrowseView

    pg = QueryBrowseView()
    qtbot.addWidget(pg)
    # 用一条 ISO 格式的 updated_at
    iso = datetime.now(UTC).isoformat(timespec="seconds")
    rows = [{"name": "q1", "updated_at": iso, "schema": "test"}]
    pg.load("p1", rows)
    cell = pg.table.item(0, 1).text()
    assert "T" not in cell and "+00:00" not in cell
    assert " " in cell
