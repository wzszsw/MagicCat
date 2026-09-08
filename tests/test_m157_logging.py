"""M157 回归：日志保留 JPype Java 原生堆栈，不改变 UI 短错误。"""

from __future__ import annotations

import io
import logging


class _JavaLikeError(RuntimeError):
    def stacktrace(self) -> str:
        return (
            "java.lang.NoClassDefFoundError: Could not initialize class Example\r\n"
            "    at com.example.Driver.connect(Driver.java:42)\r\n"
            "Caused by: java.lang.ExceptionInInitializerError\r\n"
            "    at com.example.Driver.<clinit>(Driver.java:12)"
        )


def test_java_error_short_text_is_clean_but_trace_is_complete() -> None:
    from magiccat.utils.errors import clean_java_error, exception_trace, format_exc

    exc = _JavaLikeError(
        "java.lang.NoClassDefFoundError: "
        "java.lang.NoClassDefFoundError: Could not initialize class Example"
    )

    assert clean_java_error(exc) == "Could not initialize class Example"
    assert "Could not initialize class Example" in format_exc(exc)
    assert "com.example.Driver.connect(Driver.java:42)" in exception_trace(exc)
    assert "Caused by: java.lang.ExceptionInInitializerError" in exception_trace(exc)
    assert "Python traceback:" in exception_trace(exc)


def test_log_exception_writes_java_and_python_details() -> None:
    from magiccat.utils.errors import log_exception

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("magiccat.test.m157")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        try:
            raise _JavaLikeError("driver initialization failed")
        except _JavaLikeError as exc:
            log_exception(logger, "连接失败", exc)
    finally:
        logger.removeHandler(handler)
        handler.close()

    text = stream.getvalue()
    assert "连接失败" in text
    assert "Java stack trace:" in text
    assert "Driver.java:42" in text
    assert "Python traceback:" in text
