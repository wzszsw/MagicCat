"""线程安全的 JVM 运行时单例（供 services 使用）。

约定：任何 Java 调用都必须在独立于 GUI 主线程的线程中执行（JPype 会自动 attach）；
本模块只负责"启动一次"与提供 JClass 访问。
"""

from __future__ import annotations

import threading

from magiccat.bridge.jvm import BridgeRuntime

_runtime: BridgeRuntime | None = None
_lock = threading.Lock()


def get_runtime() -> BridgeRuntime:
    """获取（必要时启动）全局唯一的 JVM 运行时。线程安全。"""
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = BridgeRuntime()
        if not _runtime.started:
            _runtime.start()
        return _runtime


def shutdown_runtime() -> None:
    """关闭 JVM（应用退出时调用；多线程场景下 JVM 会随进程终止，通常无需手动）。"""
    global _runtime
    with _lock:
        if _runtime is not None:
            _runtime.shutdown()
            _runtime = None
