"""MagicCat 资源定位：源码态 magiccat/resources/；冻结态 sys._MEIPASS/magiccat/resources。"""

from __future__ import annotations

import sys
from pathlib import Path

_RESOURCES = "magiccat/resources"


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / _RESOURCES  # PyInstaller 在冻结态注入 _MEIPASS
    return Path(__file__).resolve().parent / "resources"


def app_icon_png() -> str:
    return str(resource_dir() / "app_icon.png")


def app_icon_ico() -> str:
    return str(resource_dir() / "app_icon.ico")
