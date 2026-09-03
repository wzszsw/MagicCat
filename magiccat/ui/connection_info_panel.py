"""连接信息面板（M26）：对标 Navicat 右侧“元数据面板”。

静态项来自连接配置；动态项来自标准 JDBC DatabaseMetaData（服务端产品/版本/驱动/URL/用户等）。
数据在后台线程加载，完成回填；未选中连接时显示占位。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from magiccat.services.connection_service import ConnectionService
from magiccat.services.metadata_service import MetadataService
from magiccat.ui.job import run_async

logger = logging.getLogger(__name__)


class ConnectionInfoPanel(QWidget):
    def __init__(self, connections: ConnectionService,
                 metadata: MetadataService | None = None, parent=None) -> None:
        super().__init__(parent)
        self._connections = connections
        self._metadata = metadata or MetadataService(connections)
        self._profile_id: str | None = None

        root = QVBoxLayout(self)
        self.title = QLabel("连接信息")
        self.title.setStyleSheet("font-weight: bold;")
        root.addWidget(self.title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.form = QFormLayout(body)
        self._labels: dict[str, QLabel] = {}
        keys = [("标题", "服务器名称"), ("版本", "服务器版本"), ("产品版本号", "产品版本号"),
                ("驱动", "驱动"), ("驱动版本", "驱动版本"), ("JDBC URL", "JDBC URL"),
                ("会话用户", "用户"), ("目录术语", "目录术语"), ("模式术语", "模式术语"),
                ("事务隔离", "事务隔离"), ("主机", "主机"), ("端口", "端口"),
                ("初始数据库", "初始数据库"), ("用户名", "用户名"),
                ("配置位置", "配置文件"), ("备注", "备注")]
        for _key, text in keys:
            label = QLabel("—")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
            self._labels[text] = label
            self.form.addRow(f"{text}：", label)
        # 修复：启动时信息面板出现黑色块 —— 滚动区视口/内容开启自填充，
        # 让背景由主题决定（深色 QSS 的 QWidget 背景 / 浅色默认窗口色），
        # 避免 QScrollArea 视口在未自填充时露出未初始化的黑色底。
        body.setAutoFillBackground(True)
        scroll.viewport().setAutoFillBackground(True)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(lambda: self.show_profile(self._profile_id))
        root.addWidget(btn_refresh)

    def show_profile(self, profile_id: str | None) -> None:
        self._profile_id = profile_id
        profile = self._connections.get(profile_id) if profile_id else None
        for text in ("主机", "端口", "初始数据库", "用户名", "配置文件", "备注"):
            self._labels[text].setText("—")
        if profile is None:
            self.title.setText("连接信息（未选择）")
            for key, label in self._labels.items():
                if key not in ("主机", "端口", "初始数据库", "用户名", "配置文件", "备注"):
                    label.setText("—")
            return
        self.title.setText(f"连接信息 · {profile.display_name}")
        self._labels["主机"].setText(profile.host)
        self._labels["端口"].setText(str(profile.port))
        self._labels["初始数据库"].setText(profile.database or "（默认）")
        self._labels["用户名"].setText(profile.username)
        self._labels["配置文件"].setText(str(self._connections._store.file))

        def fetch() -> dict:
            return self._connections.server_info(profile)

        def done(info: dict) -> None:
            self._labels["服务器名称"].setText(
                f"{info.get('product', '')} {info.get('major', '')}.{info.get('minor', '')}")
            self._labels["服务器版本"].setText(str(info.get("productVersion", "")))
            self._labels["产品版本号"].setText(
                f"{info.get('major', '')}.{info.get('minor', '')}")
            self._labels["驱动"].setText(str(info.get("driver", "")))
            self._labels["驱动版本"].setText(str(info.get("driverVersion", "")))
            self._labels["JDBC URL"].setText(str(info.get("url", "")))
            self._labels["用户"].setText(str(info.get("user", "")))
            self._labels["目录术语"].setText(str(info.get("catalogTerm", "")))
            self._labels["模式术语"].setText(str(info.get("schemaTerm", "")))
            self._labels["事务隔离"].setText(str(info.get("transactionIsolation", "")))

        def error(err: str) -> None:
            logger.warning("加载连接信息失败: %s", err)
            for key in ("服务器名称", "服务器版本", "产品版本号", "驱动", "驱动版本",
                        "JDBC URL", "用户", "目录术语", "模式术语", "事务隔离"):
                self._labels[key].setText("—")

        run_async(fetch, done, error)
