"""SQL 文本工具：语句切分（带引号/注释/反引号状态机）、光标语句定位、美化。

自研状态机切分而不是依赖 sqlparse.split()，是为了拿到每条语句的原始
起止偏移，从而支持“光标所在语句”的精确识别与高亮执行。
"""

from __future__ import annotations

import sqlparse

_EMPTY_LINE_PREFIXES = ("--", "#", "/*")


def _is_empty(sql: str) -> bool:
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(_EMPTY_LINE_PREFIXES):
            return False
    return True


def split_with_offsets(text: str) -> list[tuple[int, int, str]]:
    """按顶层分号切分，返回 [(start, end, 语句文本)]（已去首尾空白）。"""
    out: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    start = 0
    state = "code"  # code | single | double | backtick | line_comment | block_comment
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "'":
                state = "single"
            elif ch == '"':
                state = "double"
            elif ch == "`":
                state = "backtick"
            elif ch == "-" and nxt == "-":
                state = "line_comment"
                i += 1
            elif ch == "#":
                state = "line_comment"
            elif ch == "/" and nxt == "*":
                state = "block_comment"
                i += 1
            elif ch == ";":
                _append_statement(text, start, i, out)
                start = i + 1
        elif state == "single":
            if ch == "\\":
                i += 1  # 跳过转义字符
            elif ch == "'":
                if nxt == "'":
                    i += 1  # '' 表示转义的单引号
                else:
                    state = "code"
        elif state == "double":
            if ch == "\\":
                i += 1
            elif ch == '"':
                if nxt == '"':
                    i += 1
                else:
                    state = "code"
        elif state == "backtick":
            if ch == "`":
                if nxt == "`":
                    i += 1
                else:
                    state = "code"
        elif state == "line_comment":
            if ch in "\r\n":
                state = "code"
        elif state == "block_comment" and ch == "*" and nxt == "/":
            state = "code"
            i += 1
        i += 1
    _append_statement(text, start, n, out)
    return out


def _append_statement(text: str, start: int, end: int,
                      out: list[tuple[int, int, str]]) -> None:
    """记录一条语句（跳过纯注释/空白段，trim 首尾空白）。"""
    s = start
    e = end
    while s < e and text[s] in " \t\r\n":
        s += 1
    while e > s and text[e - 1] in " \t\r\n":
        e -= 1
    if s < e and not _is_empty(text[s:e]):
        out.append((s, e, text[s:e]))


def split_sql_statements(text: str) -> list[str]:
    """切分为可执行语句列表（自动过滤纯注释/空白段）。"""
    return [stmt for _, _, stmt in split_with_offsets(text)]


def statement_at_cursor(text: str, pos: int) -> str | None:
    """返回光标位置所属的语句文本；光标位于语句间隙时回退到最近的前一条。"""
    segments = split_with_offsets(text)
    for start, end, stmt in segments:
        if start <= pos <= end:
            return stmt
    prev: tuple[int, int, str] | None = None
    for item in segments:
        if item[1] <= pos:
            prev = item
    return prev[2] if prev else None


def format_sql(sql: str) -> str:
    """SQL 美化（关键字大写 + 缩进）。失败时原样返回。"""
    try:
        return sqlparse.format(sql, keyword_case="upper", reindent=True, strip_comments=False)
    except Exception:  # noqa: BLE001 —— 格式化失败不影响原文本
        return sql
