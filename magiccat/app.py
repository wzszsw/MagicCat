"""MagicCat 应用入口。

当前里程碑（M1）只做技术验证骨架；PySide6 主窗口将在 M2+ 接入。
"""

from __future__ import annotations


def main() -> int:
    print(f"MagicCat {__import__('magiccat').__version__} bootstrap OK")
    print("GUI 主窗口将在后续里程碑接入（M2: 连接管理与对象浏览）")
    return 0
