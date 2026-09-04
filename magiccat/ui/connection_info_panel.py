"""连接信息/对象信息面板（M26+）：连接完整信息；选中对象时展示该对象信息（Navicat 行为）。"""

from __future__ import annotations

import logging
from typing import ClassVar

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
        btn_refresh.clicked.connect(self._refresh_current)
        root.addWidget(btn_refresh)

    def _refresh_current(self) -> None:
        if getattr(self, "_last_desc", None):
            self.show_object(self._last_desc)
        else:
            self.show_profile(self._profile_id)

    # ---- 选中对象信息（Navicat 信息面板行为） ----
    _KIND_LABEL: ClassVar[dict[str, str]] = {"database": "数据库", "table": "表",
                                             "view": "视图", "routine": "函数",
                                             "trigger": "触发器", "column": "列",
                                             "group": "分组", "category": "分类",
                                             "saved_query": "具名查询"}

    def show_object(self, desc: dict) -> None:
        """对象树选中某项 → 展示该对象信息（连接有完整信息，对象展示各自字段）。"""
        self._last_desc = desc
        kind = desc.get("kind")
        if kind == "profile":
            self.show_profile(desc.get("profile_id"))
            return
        if desc.get("profile_id"):
            self._profile_id = desc["profile_id"]
        for label in self._labels.values():
            label.setText("—")
        name = desc.get("name") or (desc.get("schema") or "")
        schema = desc.get("schema") or ""
        self._labels["服务器名称"].setText(name)
        self._labels["服务器版本"].setText(self._KIND_LABEL.get(kind, kind or ""))
        self._labels["初始数据库"].setText(schema)

        if kind == "database":
            self.title.setText(f"数据库 · {schema}")
            self._load_database_detail(schema)
        elif kind in ("table", "view"):
            self.title.setText(f"{'视图' if kind == 'view' else '表'} · {name}")
            self._load_table_detail(desc)
        elif kind == "column":
            self.title.setText(f"列 · {name}")
            detail = (f"类型：{desc.get('data_type', '')}\n可空：{desc.get('nullable', '')}\n"
                      f"默认：{desc.get('default', '')}\n注释：{desc.get('comment', '')}")
            self._labels["备注"].setText(detail)
        elif kind == "routine":
            self.title.setText(f"{'过程' if desc.get('type') == 'PROCEDURE' else '函数'} · {name}")
        elif kind == "trigger":
            self.title.setText(f"触发器 · {name}")
        elif kind == "saved_query":
            self.title.setText(f"具名查询 · {name}")

    def _profile_of_desc(self, desc: dict):
        return self._connections.get(desc.get("profile_id")) if desc.get("profile_id") else None

    def _load_database_detail(self, schema: str) -> None:
        profile = self._connections.get(self._profile_id) if self._profile_id else None
        if profile is None:
            return
        from magiccat.services.query_service import QueryService

        def fetch() -> list:
            return QueryService(self._connections).execute(profile, (
                "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
                f"FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '{schema}'"))[0]

        def done(res: dict) -> None:
            row = res.get("rows", [])
            if row:
                self._labels["备注"].setText(
                    f"默认字符集：{row[0][0]}\n默认排序规则：{row[0][1]}")

        run_async(fetch, done, lambda err: None)

    def _load_table_detail(self, desc: dict) -> None:
        profile = self._profile_of_desc(desc)
        if profile is None:
            return
        from magiccat.services.query_service import QueryService

        schema, table = desc["schema"], desc.get("table") or desc.get("name")

        def fetch() -> list:
            return QueryService(self._connections).execute(profile, (
                "SELECT t.ENGINE, t.TABLE_ROWS, t.TABLE_COLLATION, t.TABLE_COMMENT, "
                "(SELECT COUNT(*) FROM information_schema.COLUMNS c WHERE c.TABLE_SCHEMA=t.TABLE_SCHEMA "
                "AND c.TABLE_NAME=t.TABLE_NAME) AS column_count, "
                "(SELECT COUNT(DISTINCT i.INDEX_NAME) FROM information_schema.STATISTICS i "
                "WHERE i.TABLE_SCHEMA=t.TABLE_SCHEMA AND i.TABLE_NAME=t.TABLE_NAME) AS index_count "
                "FROM information_schema.TABLES t "
                f"WHERE t.TABLE_SCHEMA = '{schema}' AND t.TABLE_NAME = '{table}'"))[0]

        def done(res: dict) -> None:
            row = res.get("rows", [])
            if row:
                self._labels["备注"].setText(
                    f"引擎：{row[0][0]}\n估计行数：{row[0][1]}\n"
                    f"字符集/排序：{row[0][2]}\n注释：{row[0][3] or '-'}\n"
                    f"列数：{row[0][4]} · 索引数：{row[0][5]}")

        run_async(fetch, done, lambda err: None)

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
        self._labels["配置文件"].setText("注册表 (HKCU\\Software\\MagicCat)")

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
