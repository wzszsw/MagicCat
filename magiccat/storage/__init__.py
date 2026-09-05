"""MagicCat 跨平台本地数据目录。

目录布局遵循桌面客户端的用户文档约定：

* ``MAGICCAT_HOME`` 可显式指定数据根目录，主要用于便携模式和测试；
* Windows/macOS 使用 ``~/Documents/MagicCat``；
* Linux/Unix 优先使用 XDG 用户目录中的 ``XDG_DOCUMENTS_DIR``，缺省为
  ``~/Documents/MagicCat``。

连接配置、SQLite 缓存和 SQL 文件都位于这个根目录下，不依赖平台专有的注册表。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _documents_dir() -> Path:
    """返回当前用户的文档目录，不依赖平台专有配置注册表。"""
    home = Path.home()
    if sys.platform == "win32":
        # USERPROFILE also follows a redirected Windows user profile root.
        return Path(os.environ.get("USERPROFILE") or home) / "Documents"
    if sys.platform == "darwin":
        return home / "Documents"

    # Linux desktop environments may localize or redirect Documents through
    # the freedesktop user-dirs file.  A missing or malformed file falls back
    # to the conventional English directory.
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    user_dirs_file = config_home / "user-dirs.dirs"
    try:
        for line in user_dirs_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("XDG_DOCUMENTS_DIR="):
                continue
            value = line.partition("=")[2].strip().strip('"')
            value = value.replace("${HOME}", str(home)).replace("$HOME", str(home))
            value = os.path.expandvars(value)
            documents = Path(value).expanduser()
            return documents if documents.is_absolute() else home / documents
    except (OSError, UnicodeError):
        pass
    return home / "Documents"


def home_dir() -> Path:
    """返回 MagicCat 的用户文档数据根目录（目录按需创建）。"""
    override = os.environ.get("MAGICCAT_HOME")
    if override:
        return Path(override)
    return _documents_dir() / "MagicCat"
