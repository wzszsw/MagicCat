"""异常文案处理：清理 JPype 上抛的重复 Java 异常前缀，让 UI 提示干净可读。

典型脏文本：``java.lang.IllegalStateException: java.lang.IllegalStateException: 查询失败…``
格式入口 format_exc() 已带一次 Python 侧类型名，故把消息中的
Java 类前缀（可能多层重复）整体剥除，只留服务端真正信息。
"""

from __future__ import annotations

import logging
import re
import traceback
from types import TracebackType

_JAVA_PREFIX = re.compile(r"^(?:[\w.$]+(?:Exception|Error|Throwable): )+")


def clean_java_error(exc: BaseException | str) -> str:
    """把异常对象（或字符串）整理为一条可读消息（无 Java 类名前缀噪声）。"""
    text = str(exc)
    cleaned = _JAVA_PREFIX.sub("", text).strip()
    return cleaned if cleaned else text.strip()


def format_exc(exc: BaseException) -> str:
    """UI 错误入口：返回一行 ``类型: 信息``，不暴露完整堆栈。"""
    return f"{type(exc).__name__}: {clean_java_error(exc)}"


def java_stacktrace(exc: BaseException) -> str:
    """读取 JPype Java 异常的原生 ``printStackTrace`` 文本。

    JPype 将 Java Throwable 映射成 Python 异常，但 ``str(exc)`` 只包含
    第一行消息；``stacktrace()`` 才包含 Java 调用栈和 ``Caused by`` 链。
    普通 Python 异常没有该方法，返回空字符串。
    """
    stacktrace = getattr(exc, "stacktrace", None)
    if not callable(stacktrace):
        return ""
    try:
        value = stacktrace()
    except Exception:  # noqa: BLE001 - 诊断路径不能覆盖原始异常
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def exception_trace(
    exc: BaseException,
    tb: TracebackType | None = None,
) -> str:
    """返回适合写入文件日志的 Java + Python 完整异常信息。"""
    parts: list[str] = []
    java_trace = java_stacktrace(exc)
    if java_trace:
        parts.append("Java stack trace:\n" + java_trace)

    python_trace = "".join(
        traceback.format_exception(type(exc), exc, tb if tb is not None else exc.__traceback__)
    ).strip()
    if python_trace:
        parts.append("Python traceback:\n" + python_trace)
    return "\n\n".join(parts) or format_exc(exc)


def log_exception(
    logger: logging.Logger,
    message: str,
    exc: BaseException,
    *,
    level: int = logging.ERROR,
    tb: TracebackType | None = None,
) -> None:
    """写入完整异常，同时保持调用方的短 UI 错误文案独立。"""
    details = exception_trace(exc, tb)
    logger.log(level, "%s\n%s", message, details)
