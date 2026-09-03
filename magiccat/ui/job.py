"""后台任务封装：JDBC 调用禁止在 GUI 主线程执行（见设计方案 §3.3/§5.3）。

用法：
    run_async(fn, on_done=cb, on_error=err_cb)
fn 在工作线程执行（首次调用 Java 时 JPype 自动 attach），结果经信号回主线程。

注意：QRunnable 执行完即被 QThreadPool 回收，若信号 QObject 随任务销毁，
已入队的跨线程信号会被 Qt 丢弃 —— 因此模块级 _pending 持有引用直至回调执行。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Signals(QObject):
    done = Signal(object)
    error = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _Signals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 —— 边界错误统一走 error 信号
            self._signals.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self._signals.done.emit(result)


# 引用持有：防止 worker 完成、QObject 被回收时丢弃尚未投递的信号
_pending: set[_Signals] = set()


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """在工作线程执行 fn，结果/错误回调自动回到主线程。"""
    signals = _Signals()
    _pending.add(signals)

    def _release(*_args: Any) -> None:
        _pending.discard(signals)

    signals.done.connect(_release)
    signals.error.connect(_release)
    if on_done is not None:
        signals.done.connect(on_done)
    if on_error is not None:
        signals.error.connect(on_error)
    QThreadPool.globalInstance().start(_Task(fn, signals))
