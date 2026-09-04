"""本地存储根目录与注册表根键的统一定位（对标 Navicat，三合一存储）。

- 根目录：`$MAGICCAT_HOME`（未设置则 `%APPDATA%\\MagicCat`）。
- 注册表根：`HKCU\\Software\\MagicCat`（连接配置，含 DPAPI 密码）。
- SQLite 库：`<root>/metacache.db`（元数据缓存/历史/收藏/窗口状态）。
- 查询 SQL：文件系统 `.sql`（`<root>/<conn>/<schema>/<name>.sql`）。
"""

from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    """MagicCat 数据根目录。优先 $MAGICCAT_HOME，否则 %APPDATA%\\MagicCat。"""
    override = os.environ.get("MAGICCAT_HOME")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "MagicCat"


def registry_root() -> str:
    """Windows 注册表根键路径（HKCU 下）。"""
    return r"Software\MagicCat"


def registry_servers_key() -> str:
    """连接配置注册表子键（HKCU\\Software\\MagicCat\\Servers）。"""
    return registry_root() + r"\Servers"
