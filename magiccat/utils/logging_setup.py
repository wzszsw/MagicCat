"""日志配置：控制台 + 文件（MAGICCAT_HOME/logs/magiccat.log，UTF-8）。"""

from __future__ import annotations

import logging
from pathlib import Path

_HANDLER_NAME = "magiccat-file"


def configure_logging(root: Path | None = None, level: int = logging.INFO) -> None:
    """幂等配置根 logger（不重复挂 handler）。"""
    root = root or _default_root()
    logger = logging.getLogger()
    if any(getattr(h, "name", "") == _HANDLER_NAME for h in logger.handlers):
        return
    logger.setLevel(level)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(console)
    try:
        logs_dir = root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(logs_dir / "magiccat.log", encoding="utf-8")
        handler.name = _HANDLER_NAME
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    except OSError:
        pass  # 日志目录不可写时仅控制台


def _default_root() -> Path:
    from magiccat.storage import home_dir

    return home_dir()
