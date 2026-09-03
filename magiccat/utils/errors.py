"""异常文案处理：清理 JPype 上抛的重复 Java 异常前缀，让 UI 提示干净可读。

典型脏文本：``java.lang.IllegalStateException: java.lang.IllegalStateException: 查询失败…``
格式入口 format_exc() 已带一次 Python 侧类型名，故把消息中的
Java 类前缀（可能多层重复）整体剥除，只留服务端真正信息。
"""

from __future__ import annotations

import re

_JAVA_PREFIX = re.compile(r"^(?:[\w.]+Exception: )+")


def clean_java_error(exc: BaseException | str) -> str:
    """把异常对象（或字符串）整理为一条可读消息（无 Java 类名前缀噪声）。"""
    text = str(exc)
    cleaned = _JAVA_PREFIX.sub("", text).strip()
    return cleaned if cleaned else text.strip()


def format_exc(exc: BaseException) -> str:
    """UI/日志统一入口：``类型: 信息``。"""
    return f"{type(exc).__name__}: {clean_java_error(exc)}"
