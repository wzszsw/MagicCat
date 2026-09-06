"""MagicCat 启动画面。

主窗口等待首个 Monaco WebEngine 页面初始化时显示此独立窗口，避免把初始化
耗时误认为程序没有响应，也避免主窗口先显示后发生白闪。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QWidget

from magiccat import __version__
from magiccat.resources import app_icon_png


class StartupSplash(QWidget):
    """无边框启动画面，显示产品标识和初始化进度指示。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint,
        )
        self.setFixedSize(520, 340)
        self.setWindowTitle("MagicCat")
        self.setWindowIcon(QIcon(app_icon_png()))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._angle = 0
        self._logo = QPixmap(app_icon_png())
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._advance)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.move(available.center() - self.rect().center())
        self._timer.start()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:  # pragma: no cover - 视觉绘制
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FCFAF2"))

        # 底部两层柔和曲线，借鉴 Navicat 启动画面的留白和层次。
        path = QPainterPath()
        path.moveTo(0, 273)
        path.cubicTo(90, 233, 145, 293, 250, 263)
        path.cubicTo(355, 233, 425, 283, 520, 253)
        path.lineTo(520, 340)
        path.lineTo(0, 340)
        path.closeSubpath()
        painter.fillPath(path, QColor("#FFF3C8"))
        path = QPainterPath()
        path.moveTo(0, 307)
        path.cubicTo(90, 277, 165, 327, 270, 295)
        path.cubicTo(380, 262, 430, 317, 520, 287)
        path.lineTo(520, 340)
        path.lineTo(0, 340)
        path.closeSubpath()
        painter.fillPath(path, QColor("#FFEDB5"))

        logo = self._logo.scaled(78, 78, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((self.width() - logo.width()) // 2, 34, logo)

        def draw_centered(text: str, font: QFont, color: QColor, center_y: float) -> None:
            painter.setFont(font)
            metrics = QFontMetricsF(font)
            baseline = center_y + (metrics.ascent() - metrics.descent()) / 2
            x = (self.width() - metrics.horizontalAdvance(text)) / 2
            painter.setPen(color)
            painter.drawText(QPointF(x, baseline), text)

        title_font = QFont("Segoe UI")
        title_font.setPointSize(28)
        title_font.setWeight(QFont.Weight.Medium)
        draw_centered("MagicCat", title_font, QColor("#3F4A52"), 143)

        subtitle_font = QFont("Segoe UI")
        subtitle_font.setPointSize(11)
        subtitle_font.setWeight(QFont.Weight.DemiBold)
        subtitle_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        draw_centered("DATABASE TOOL", subtitle_font, QColor("#D6A929"), 181)

        detail_font = QFont("Segoe UI")
        detail_font.setPointSize(10)
        draw_centered(f"版本 {__version__} · 正在启动", detail_font,
                      QColor("#59636A"), 216)

        center_x, center_y = self.width() // 2, 247
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(self._angle)
        for index in range(8):
            painter.save()
            painter.rotate(index * 45)
            alpha = 255 - index * 25
            painter.setPen(QPen(QColor(214, 169, 41, max(alpha, 55)), 3))
            painter.drawLine(0, -8, 0, -14)
            painter.restore()
        painter.restore()

        footer_font = QFont("Segoe UI")
        footer_font.setPointSize(9)
        draw_centered("正在初始化本地编辑器...", footer_font,
                      QColor("#59636A"), 321)
        painter.end()
