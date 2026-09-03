"""ER 图查看器（M6）：库内表关系自动布局渲染，支持导出 PNG。

数据加载在后台线程（一次拉取全部表/列/外键），完成后绘制 QGraphicsScene。
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.er_model import build_er_model
from magiccat.services.metadata_service import MetadataService
from magiccat.ui.job import run_async

COL_W = 210
ROW_H = 18
HEAD_H = 24
PAD_X = 60
PAD_Y = 40


class ErView(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing)

    def render_model(self, model) -> None:
        self._scene.clear()
        n = len(model.tables)
        cols = max(1, math.ceil(math.sqrt(max(n, 1))))
        row_h = max((t.height for t in model.tables), default=200) + 90
        pen = QPen(QColor("#888888"))
        font = QFont("Microsoft YaHei", 9)
        boxes: dict[str, tuple[float, float, float, float]] = {}

        for i, t in enumerate(model.tables):
            x = (i % cols) * (COL_W + PAD_X) + PAD_X
            y = (i // cols) * row_h + PAD_Y
            height = max(t.height, HEAD_H + 10)
            rect = QGraphicsRectItem(0, 0, COL_W, height)
            rect.setPos(x, y)
            rect.setPen(pen)
            rect.setBrush(QColor("#E8EEF7"))
            self._scene.addItem(rect)

            title = QGraphicsTextItem(t.name)
            title.setFont(QFont("Microsoft YaHei", 10))
            title.setPos(x + 6, y + 3)
            self._scene.addItem(title)

            yy = y + HEAD_H
            for c in t.columns:
                text = ("🔑 " if c.get("key") == "PRI" else "   ") + c["name"]
                item = QGraphicsTextItem(text)
                item.setFont(font)
                item.setPos(x + 4, yy)
                self._scene.addItem(item)
                yy += ROW_H
            boxes[t.name] = (x, y, COL_W, height)

        # 外键连线：child(下边中) → parent(左边中部)
        for fk in model.fks:
            child = boxes.get(fk.child_table)
            parent = boxes.get(fk.parent_table)
            if not child or not parent:
                continue
            x1 = child[0] + child[2] / 2
            y1 = child[1] + child[3] + 8
            x2 = parent[0] - 8
            y2 = parent[1] + parent[3] / 2
            mid = (x1 + x2) / 2
            # 折线：垂直下 → 水平 → 上
            pp = QPainterPath()
            pp.moveTo(x1, y1)
            pp.lineTo(mid, y1)
            pp.lineTo(mid, y2)
            pp.lineTo(x2, y2)
            path = self._scene.addPath(pp)
            path.setPen(QPen(QColor("#C0504D"), 1.2))
            label = QGraphicsTextItem(f"{fk.child_col} → {fk.parent_table}.{fk.parent_col}")
            label.setFont(QFont("Microsoft YaHei", 7))
            label.setDefaultTextColor(QColor("#A0522D"))
            label.setPos(mid + 4, (y1 + y2) / 2)
            self._scene.addItem(label)

        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def fit(self) -> None:
        if self._scene.items():
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def export_png(self, path: str) -> None:
        rect = self._scene.sceneRect()
        image = QImage(int(rect.width()), int(rect.height()), QImage.Format_ARGB32)
        image.fill(QColor("#FFFFFF"))
        painter = QPainter(image)
        self._scene.render(painter)
        painter.end()
        image.save(path)


class ErDialog(QDialog):
    def __init__(self, profile: ConnectionProfile, schema: str,
                 connections: ConnectionService, parent=None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.schema = schema
        self._connections = connections
        self._metadata = MetadataService(connections)
        self.setWindowTitle(f"ER 图 · {schema}（{profile.name}）")
        self.resize(1100, 760)
        root = QVBoxLayout(self)
        self.status = QLabel("加载中…")
        root.addWidget(self.status)
        self.view = ErView()
        root.addWidget(self.view, 1)
        bar = QHBoxLayout()
        btn_fit = QPushButton("适配窗口")
        btn_png = QPushButton("导出 PNG…")
        btn_close = QPushButton("关闭")
        for b in (btn_fit, btn_png, btn_close):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)
        btn_fit.clicked.connect(self.view.fit)
        btn_png.clicked.connect(self._export_png)
        btn_close.clicked.connect(self.accept)
        self._load()

    def _load(self) -> None:
        profile, schema = self.profile, self.schema

        def fetch() -> object:
            tables = [t for t in self._metadata.tables(profile, schema)
                      if t["type"] == "BASE TABLE"]
            if not tables:
                return None
            columns_of = {}
            fk_rows_of = {}
            for t in tables:
                columns_of[t["name"]] = self._metadata.columns(profile, schema, t["name"])
                fk_rows_of[t["name"]] = self._metadata.foreign_keys(profile, schema, t["name"])
            return build_er_model(schema, tables, columns_of, fk_rows_of)

        def done(model) -> None:
            if model is None:
                self.status.setText("该库没有基础表，无法绘制 ER 图")
                return
            self.view.render_model(model)
            self.status.setText(
                f"{len(model.tables)} 张表 · {len(model.fks)} 条外键关系")

        def error(err: str) -> None:
            self.status.setText(f"加载失败：{err}")

        run_async(fetch, done, error)

    def _export_png(self) -> None:
        path, _f = QFileDialog.getSaveFileName(self, "导出 ER 图", f"{self.schema}_er.png",
                                               "PNG 图片 (*.png)")
        if not path:
            return
        self.view.export_png(path)
        QMessageBox.information(self, "导出 ER 图", f"已保存：{path}")
