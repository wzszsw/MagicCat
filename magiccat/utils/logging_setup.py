"""日志配置：控制台（调试）+ 滚动文件（MAGICCAT_HOME/logs/magiccat.log）。"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_HANDLER_NAME = "magiccat-file"
_CONSOLE_HANDLER_NAME = "magiccat-console"
_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5
_hooks_installed = False


def configure_logging(root: Path | None = None, level: int = logging.INFO) -> None:
    """幂等配置根 logger、滚动文件和未捕获异常钩子。"""
    root = root or _default_root()
    logger = logging.getLogger()
    logger.setLevel(level)

    # --windowed 正式包没有可用控制台；调试运行仍保留 stderr 输出。
    if sys.stderr is not None and not any(
        getattr(h, "name", "") == _CONSOLE_HANDLER_NAME for h in logger.handlers
    ):
        console = logging.StreamHandler()
        console.name = _CONSOLE_HANDLER_NAME
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(console)

    try:
        logs_dir = root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        if not any(getattr(h, "name", "") == _HANDLER_NAME for h in logger.handlers):
            handler = RotatingFileHandler(
                logs_dir / "magiccat.log",
                maxBytes=_MAX_LOG_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
                delay=True,
            )
            handler.name = _HANDLER_NAME
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"))
            logger.addHandler(handler)
    except OSError:
        # 日志目录不可写时保留控制台；windowed 包仍由异常钩子尽力记录。
        pass

    _install_exception_hooks()


def _install_exception_hooks() -> None:
    """把主线程和后台线程未捕获异常写入完整诊断日志。"""
    global _hooks_installed
    if _hooks_installed:
        return

    from magiccat.utils.errors import log_exception

    logger = logging.getLogger("magiccat.unhandled")
    previous_sys_hook = sys.excepthook

    def handle_sys_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            if sys.stderr is not None:
                previous_sys_hook(exc_type, exc_value, exc_tb)
            return
        log_exception(logger, "未捕获的主线程异常", exc_value, tb=exc_tb)
        if sys.stderr is not None:
            previous_sys_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_sys_exception

    previous_thread_hook = threading.excepthook

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        thread_name = args.thread.name if args.thread is not None else "unknown"
        log_exception(
            logger,
            f"未捕获的线程异常（{thread_name}）",
            args.exc_value,
            tb=args.exc_traceback,
        )
        if sys.stderr is not None:
            previous_thread_hook(args)

    threading.excepthook = handle_thread_exception
    _hooks_installed = True


def _default_root() -> Path:
    from magiccat.storage import home_dir

    return home_dir()
