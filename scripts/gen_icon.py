"""生成应用图标（纯 Qt 绘制，无第三方图像库）：PNG + 兼容 ICO（内嵌 PNG）。

用法：uv run python scripts/gen_icon.py
输出：magiccat/resources/app_icon.png / app_icon.ico
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "magiccat" / "resources"

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

SIZES = [256, 64, 48, 32, 16]


def draw_icon(size: int) -> bytes:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    radius = size * 0.22
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2F6DB5"))
    p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setBrush(QColor("#5B9BD5"))
    p.drawRoundedRect(QRectF(0, 0, size, size * 0.55), radius, radius * 0.7)
    p.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(int(size * 0.55))
    p.setFont(font)
    p.drawText(QRectF(0, size * 0.08, size, size * 0.85), Qt.AlignCenter, "MC")
    p.end()
    return _png_bytes(image)


def _png_bytes(image: QImage) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    return bytes(ba.data())


def build_ico(pngs: dict[int, bytes]) -> bytes:
    """ICO 容器：每尺寸一个内嵌 PNG 条目（Vista+ 支持）。"""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries = b""
    offset = 6 + 16 * len(pngs)
    for size in sorted(pngs, reverse=True):
        data = pngs[size]
        b = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return header + entries + b"".join(pngs[s] for s in sorted(pngs, reverse=True))


def main() -> int:
    QGuiApplication(sys.argv)  # 字体/绘制需要 QGui 上下文
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pngs = {s: draw_icon(s) for s in SIZES}
    (OUT_DIR / "app_icon.png").write_bytes(pngs[256])
    (OUT_DIR / "app_icon.ico").write_bytes(build_ico(pngs))
    print(f"生成完成：{OUT_DIR / 'app_icon.png'} / {OUT_DIR / 'app_icon.ico'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
