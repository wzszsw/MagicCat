"""MagicCat 跨平台本地数据目录。

目录布局遵循桌面客户端的用户数据约定：

* ``MAGICCAT_HOME`` 可显式指定数据根目录，主要用于便携模式和测试；
* Windows 使用 ``%APPDATA%/MagicCat``；
* macOS 使用 ``~/Library/Application Support/MagicCat``；
* Linux/Unix 使用 ``$XDG_CONFIG_HOME/MagicCat``，缺省为 ``~/.config/MagicCat``。

连接配置、SQLite 缓存和 SQL 文件都位于这个根目录下，不依赖平台专有的注册表。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def home_dir() -> Path:
    """返回 MagicCat 的用户数据根目录（目录按需创建）。"""
    override = os.environ.get("MAGICCAT_HOME")
    if override:
        return Path(override)

    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base) / "MagicCat" if base else Path.home() / "AppData" / "Roaming" / "MagicCat"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MagicCat"

    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base) / "MagicCat" if base else Path.home() / ".config" / "MagicCat"
