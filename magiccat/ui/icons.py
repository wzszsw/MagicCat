"""自有矢量小图标（Qt 自绘，无第三方版权；商业可安全使用）。

色彩参考 Navicat 常见配色，16px 供对象树/列表使用：
  - 函数 fx（蓝）、存储过程 P（绿）、表(蓝网格)、视图(橙)、触发器(黄闪电)、
  - 数据库(绿圆柱)、连接(服务器)、查询/收藏夹(蓝相)、分组/夹(米黄)。
所有图标由 QPainter 绘制并缓存；未知类型返回 None（Qt 使用默认）。
"""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF

_SIZE = 16

_COLORS = {
    "blue": "#3B82F6",
    "green": "#4E9A5A",
    "orange": "#E8A33D",
    "yellow": "#F5C518",
    "slate": "#6B7280",
    "cream": "#E7C77B",
    "dark": "#333537",
}


def _canvas() -> QImage:
    image = QImage(_SIZE, _SIZE, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    return image


def _painter(image: QImage) -> QPainter:
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    return p


def _bdg(p: QPainter, color: str, radius: float = 3.0) -> None:
    p.setPen(QPen(QColor("#2B2F36"), 1.0))
    p.setBrush(QBrush(QColor(color)))
    p.drawRoundedRect(QRectF(0.5, 0.5, _SIZE - 1, _SIZE - 1), radius, radius)


def _text(p: QPainter, text: str, px: int, color: str, bold: bool = True) -> None:
    from PySide6.QtGui import QFont

    font = QFont("Segoe UI")
    font.setPixelSize(px)
    font.setBold(bold)
    p.setFont(font)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, _SIZE, _SIZE), Qt.AlignCenter, text)


def _function() -> QImage:
    image = _canvas()
    p = _painter(image)
    _bdg(p, _COLORS["blue"], 4.0)
    _text(p, "fx", 9, "#FFFFFF")
    p.end()
    return image


def _procedure() -> QImage:
    image = _canvas()
    p = _painter(image)
    _bdg(p, _COLORS["green"], 4.0)
    _text(p, "P", 10, "#FFFFFF")
    p.end()
    return image


def _table() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#2B5F9E"), 1.0))
    p.setBrush(QBrush(QColor(_COLORS["blue"])))
    p.drawRoundedRect(QRectF(1, 2.5, _SIZE - 2, _SIZE - 4), 2, 2)
    p.setPen(QPen(QColor("#FFFFFF"), 1.0))
    for x in (5.3, 9.3):
        p.drawLine(x, 3, x, _SIZE - 2)
    p.drawLine(1, 6.5, _SIZE - 1, 6.5)
    p.end()
    return image


def _view() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#A66B1F"), 1.0))
    p.setBrush(QBrush(QColor(_COLORS["orange"])))
    p.drawEllipse(QRectF(2, 3.5, _SIZE - 4, _SIZE - 7))
    p.setBrush(QBrush(QColor(_COLORS["dark"])))
    p.drawEllipse(QRectF(6, 6, 4, 4))
    p.end()
    return image


def _trigger() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(_COLORS["yellow"])))
    p.drawPolygon(QPolygonF([
        QPointF(9, 0.5), QPointF(4, 9), QPointF(7.5, 9),
        QPointF(6, 15.5), QPointF(12, 7), QPointF(8.5, 7)]))
    p.end()
    return image


def _database() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#2B5F2E"), 1.0))
    p.setBrush(QBrush(QColor(_COLORS["green"])))
    p.drawEllipse(QRectF(1.5, 1.5, _SIZE - 3, 4.5))
    p.drawRect(QRectF(1.5, 3, _SIZE - 3, 9))
    p.setBrush(QBrush(QColor("#76C97A")))
    p.drawEllipse(QRectF(1.5, 10.5, _SIZE - 3, 4.5))
    p.end()
    return image


def _connection() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#33506B"), 1.0))
    p.setBrush(QBrush(QColor("#7FA9C9")))
    p.drawRoundedRect(QRectF(2, 2, _SIZE - 4, _SIZE - 4), 3, 3)
    p.setBrush(QBrush(QColor("#3B82F6")))
    p.drawEllipse(QRectF(5.5, 5.5, 5, 5))
    p.end()
    return image


def _folder(color: str) -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#8A6D1F"), 1.0))
    p.setBrush(QBrush(QColor(color)))
    p.drawRoundedRect(QRectF(1, 4, _SIZE - 2, 9), 2, 2)
    p.drawRect(QRectF(1, 3, 6, 3))
    p.end()
    return image


def _query() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#3E5F86"), 1.4))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(2, 2, 8.5, 8.5))
    p.drawLine(9.5, 9.5, 13.5, 13.5)
    p.end()
    return image


@cache
def _icon_image(kind: str, subtype: str = "") -> QImage | None:
    if kind == "function" or (kind == "routine" and subtype != "PROCEDURE"):
        return _function()
    if kind == "procedure" or (kind == "routine" and subtype == "PROCEDURE"):
        return _procedure()
    if kind == "table":
        return _table()
    if kind == "view":
        return _view()
    if kind == "trigger":
        return _trigger()
    if kind in ("database", "schema"):
        return _database()
    if kind == "profile" or kind == "connection":
        return _connection()
    if kind == "saved_query":
        return _query()
    if kind in ("query_folder", "category"):
        return _folder(_COLORS["cream"])
    if kind == "group":
        return _folder(_COLORS["cream"])
    return None


@cache
def icon(kind: str, subtype: str = "") -> QIcon:
    """按 kind/subtype 返回 QIcon；未知类型返回空图标。"""
    img = _icon_image(kind, subtype)
    if img is None:
        return QIcon()
    return QIcon(QPixmap.fromImage(img))
