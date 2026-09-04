"""日期时间格式化：统一显示为 `YYYY-MM-DD HH:MM:SS`（本地时区）。

数据侧 `updated_at` 等存的是 `datetime.now(UTC).isoformat(timespec="seconds")`
（形如 `2026-09-04T10:55:08+00:00`）；展示时统一转成无 `T`、无时区偏移、
本地时区的「年-月-日 时:分:秒」。非日期字符串原样返回。
"""

from __future__ import annotations

from datetime import datetime


def format_datetime(value: str) -> str:
    """把 ISO 日期字符串转成 `YYYY-MM-DD HH:MM:SS`；无法解析则原样返回。"""
    if not value:
        return value
    text = value.strip()
    # 只处理含日期特征的字符串（ISO 里 T 或完整日期）
    if len(text) < 10 or ("T" not in text and ("-" not in text[:10])):
        return value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return value
    # 归一为本地时间再格式化
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")
