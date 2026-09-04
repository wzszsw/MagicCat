"""对象树加载状态：显示一个旋转的 loading 动画图标（对标 Navicat 的连接加载）。

- 自绘 16px spinner（透明背景圆弧 + 扇头），用 QTimer 逐帧旋转，无需外部 gif。
- start_loading(item)：开启该节点的 loading 图标动画（存原图标，结束恢复）。
- stop_loading(item)：停止动画，恢复原图标。
- 内部按 item id 管理定时器；重复 start 同节点不会叠加。
"""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QTreeWidgetItem

_SIZE = 16
_STEPS = 12
_INTERVAL_MS = 80


def _frame(angle: float) -> QPixmap:
    image = QImage(_SIZE, _SIZE, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    # 背景细弧（淡灰）
    p.setPen(QPen(QColor("#C0C4CC"), 1.6))
    p.drawArc(QRectF(2, 2, _SIZE - 4, _SIZE - 4), 0, 300 * 16)
    # 当前扇头（蓝色，随角度旋转）
    p.setPen(QPen(QColor("#3B82F6"), 1.8))
    p.drawArc(QRectF(2, 2, _SIZE - 4, _SIZE - 4), int(angle * 16), 90 * 16)
    p.end()
    return QPixmap.fromImage(image)


@cache
def _frames() -> list[QPixmap]:
    return [_frame(i * 360 / _STEPS) for i in range(_STEPS)]


class _LoaderState:
    """单个节点的 loading 动画状态。"""
    __slots__ = ("idx", "item", "orig_icon", "timer")

    def __init__(self, item: QTreeWidgetItem) -> None:
        self.item = item
        self.orig_icon = item.icon(0)
        self.idx = 0
        self.timer = QTimer()
        self.timer.setInterval(_INTERVAL_MS)
        self.timer.timeout.connect(self._tick)
        self.item.setIcon(0, _frames()[0])
        self.timer.start()

    def _tick(self) -> None:
        self.idx = (self.idx + 1) % _STEPS
        if self.item.treeWidget() is not None:  # 节点可能已被删除
            self.item.setIcon(0, _frames()[self.idx])

    def stop(self) -> None:
        self.timer.stop()
        if self.item.treeWidget() is not None:
            self.item.setIcon(0, self.orig_icon)


_active: dict[int, _LoaderState] = {}


def start_loading(item: QTreeWidgetItem) -> None:
    if item is None:
        return
    if id(item) in _active:
        return
    _active[id(item)] = _LoaderState(item)


def stop_loading(item: QTreeWidgetItem) -> None:
    if item is None:
        return
    state = _active.pop(id(item), None)
    if state is not None:
        state.stop()
