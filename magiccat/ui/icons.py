"""图标。

- 通用对象树/列表小图标：Qt 自绘（QPainter），无第三方版权，商业可安全使用。
- 数据库产品连接图标：优先使用 devicon 彩色 logo PNG 资产（MIT 许可，
  见 magiccat/resources/logos/），缺失或未知产品回退到自绘图标。
所有图标按 kind/subtype 分发并缓存；未知类型返回 None（Qt 使用默认）。
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


# ---- 数据库产品连接图标（自绘，无第三方依赖；按 provider_key 路由） ----

def _conn_mysql() -> QImage:
    """MySQL：绿色椭圆形牌 + 白色海豚剪影抽象。"""
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#2E7D32"), 1.0))
    p.setBrush(QBrush(QColor("#00758F")))  # MySQL 品牌色
    p.drawEllipse(QRectF(2, 2, _SIZE - 4, _SIZE - 4))
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.drawEllipse(QRectF(4.5, 5.5, 4, 4))  # 头
    p.drawRoundedRect(QRectF(7, 8, 4.5, 3), 1, 1)  # 身
    p.end()
    return image


def _conn_postgres() -> QImage:
    """PostgreSQL：蓝色牌 + 白色大象头抽象。"""
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#1E4E79"), 1.0))
    p.setBrush(QBrush(QColor("#336791")))  # PostgreSQL 品牌色
    p.drawRoundedRect(QRectF(2, 2, _SIZE - 4, _SIZE - 4), 3, 3)
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.drawRoundedRect(QRectF(5, 5, 4.5, 4.5), 2, 2)  # 头
    p.drawRoundedRect(QRectF(8.5, 6, 3, 2.5), 1, 1)  # 鼻
    p.drawRect(QRectF(4.5, 9.5, 2.5, 3))  # 耳
    p.end()
    return image


def _conn_mariadb() -> QImage:
    """MariaDB：黄绿色牌 + 海豚（与 MySQL 区分色）。"""
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#6A7A1E"), 1.0))
    p.setBrush(QBrush(QColor("#A9BA26")))
    p.drawEllipse(QRectF(2, 2, _SIZE - 4, _SIZE - 4))
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.drawEllipse(QRectF(4.5, 5.5, 4, 4))
    p.drawRoundedRect(QRectF(7, 8, 4.5, 3), 1, 1)
    p.end()
    return image


def _conn_oracle() -> QImage:
    """Oracle：红色牌 + 白色「O」标志。"""
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#8A0D0D"), 1.0))
    p.setBrush(QBrush(QColor("#C74634")))  # Oracle 红
    p.drawRoundedRect(QRectF(2, 2, _SIZE - 4, _SIZE - 4), 3, 3)
    p.setPen(QPen(QColor("#FFFFFF"), 2.0))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(4.5, 4.5, 7, 7))
    p.end()
    return image


def _conn_sqlserver() -> QImage:
    """SQL Server：青色牌 + 白色数据立方。"""
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#1F3A4A"), 1.0))
    p.setBrush(QBrush(QColor("#2E5A77")))
    p.drawRoundedRect(QRectF(2, 2, _SIZE - 4, _SIZE - 4), 3, 3)
    p.setBrush(QBrush(QColor("#5CBAE0")))
    p.drawRect(QRectF(4, 4.5, 8, 7))  # 立方主体
    p.setPen(QPen(QColor("#FFFFFF"), 1.0))
    p.drawLine(4, 4.5, 8, 7)  # 斜线示意数据
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


def _run() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor("#4E9A5A")))
    p.drawPolygon(QPolygonF([QPointF(3.5, 2), QPointF(13.5, 8), QPointF(3.5, 14)]))
    p.end()
    return image


def _stop() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#8A3B3B"), 1.0))
    p.setBrush(QBrush(QColor("#D9534F")))
    p.drawRoundedRect(QRectF(3, 3, 10, 10), 2, 2)
    p.end()
    return image


def _new_query() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#2B5F9E"), 1.0))
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.drawRoundedRect(QRectF(2.5, 1.5, 9, 12), 1, 1)
    p.setPen(QPen(QColor("#3B82F6"), 1.0))
    for y in (4.5, 7.0, 9.5):
        p.drawLine(4.5, y, 9.5, y)
    p.setBrush(QBrush(QColor("#F5C518")))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(9.5, 9.5, 5.5, 5.5))
    p.end()
    return image


def _save() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#2E5A77"), 1.0))
    p.setBrush(QBrush(QColor("#7EB8DC")))
    p.drawRoundedRect(QRectF(2.5, 2, 11, 12), 2, 2)
    p.setBrush(QBrush(QColor("#FFFFFF")))
    p.drawRect(QRectF(4.5, 3.5, 7, 4.5))
    p.drawRect(QRectF(4.5, 9.5, 7, 3.5))
    p.end()
    return image


def _user() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor("#E8A33D")))
    p.drawEllipse(QRectF(5, 2, 6, 6))
    p.drawChord(QRectF(3, 9, 10, 9), 0, 180 * 16)
    p.end()
    return image


def _other() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#4B5563"), 1.0))
    p.setBrush(QBrush(QColor("#9CA3AF")))
    p.drawRoundedRect(QRectF(2, 5, 12, 8.5), 2, 2)
    p.drawRect(QRectF(5, 3, 6, 3))
    p.setBrush(QBrush(QColor("#3B82F6")))
    p.drawEllipse(QRectF(7, 8, 2.5, 2.5))
    p.end()
    return image


def _sequence() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#5B4A8A"), 1.0))
    p.setBrush(QBrush(QColor("#9B59B6")))
    p.drawRoundedRect(QRectF(2.5, 2.5, 11, 11), 2, 2)
    p.setPen(QPen(QColor("#FFFFFF"), 1.0))
    p.drawLine(5.5, 8, 10.5, 8)
    p.drawLine(8, 5.5, 8, 10.5)
    p.end()
    return image


def _backup() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#2B5F2E"), 1.0))
    p.setBrush(QBrush(QColor(_COLORS["green"])))
    p.drawEllipse(QRectF(2, 2, 12, 4.5))
    p.drawRect(QRectF(2, 3.5, 12, 8))
    p.setBrush(QBrush(QColor("#76C97A")))
    p.drawEllipse(QRectF(2, 9.5, 12, 4.5))
    p.end()
    return image


def _auto_run() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#2E5A77"), 1.4))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(2, 2, 12, 12))
    p.drawLine(8, 8, 8, 4.5)
    p.drawLine(8, 8, 11, 9.5)
    p.end()
    return image


def _model() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(QPen(QColor("#5B2E7A"), 1.0))
    p.setBrush(QBrush(QColor("#9B59B6")))
    for x, y in ((2, 2), (9, 2), (2, 9), (9, 9)):
        p.drawRoundedRect(QRectF(x, y, 5, 5), 1, 1)
    p.end()
    return image


def _bi() -> QImage:
    image = _canvas()
    p = _painter(image)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor("#7C3AED")))
    p.drawRect(QRectF(2, 8, 3, 6))
    p.drawRect(QRectF(6.5, 5, 3, 9))
    p.drawRect(QRectF(11, 2, 3, 12))
    p.end()
    return image


@cache
def _conn_by_provider(provider_key: str) -> QImage | None:
    """按数据库产品 key 返回连接图标。

    优先加载 devicon 彩色 logo PNG 资产（MIT 许可，见 magiccat/resources/logos/）；
    资产缺失（如未打包资源/未知产品）回退到自绘图标。
    """
    logo = _logo_image(provider_key)
    if logo is not None:
        return logo
    return {
        "mysql": _conn_mysql(),
        "postgresql": _conn_postgres(),
        "mariadb": _conn_mariadb(),
        "oracle": _conn_oracle(),
        "sqlserver": _conn_sqlserver(),
    }.get(provider_key, _connection())


@cache
def _logo_image(provider_key: str) -> QImage | None:
    """从资源目录读取产品 logo PNG。

    优先用 64px（矢量源头渲染，Qt 缩放到 16/32 目标更清晰），缺失再回退 32px。
    文件缺失/读取失败返回 None（由调用方回退自绘图标）。
    """
    from magiccat.resources import resource_dir

    base = resource_dir() / "logos"
    for size in (64, 32, 16):
        path = base / f"{provider_key}-{size}.png"
        if path.exists():
            img = QImage(str(path))
            if not img.isNull():
                return img
    return None


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
    if kind in ("profile", "connection"):
        return _conn_by_provider(subtype)
    if kind in ("saved_query", "query"):
        return _query()
    if kind == "run":
        return _run()
    if kind == "stop":
        return _stop()
    if kind == "new_query":
        return _new_query()
    if kind == "save":
        return _save()
    if kind == "user":
        return _user()
    if kind == "other":
        return _other()
    if kind == "sequence":
        return _sequence()
    if kind == "backup":
        return _backup()
    if kind == "auto_run":
        return _auto_run()
    if kind == "model":
        return _model()
    if kind == "bi":
        return _bi()
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
