"""主窗口（M2 骨架）：左侧对象浏览器 + 中央占位 + 连接管理动作。"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from magiccat.services.connection_service import ConnectionService
from magiccat.services.metadata_service import MetadataService
from magiccat.ui.dialogs import ConnectionEditDialog
from magiccat.ui.job import run_async
from magiccat.ui.object_explorer import ObjectExplorer

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, connections: ConnectionService,
                 metadata: MetadataService | None = None) -> None:
        super().__init__()
        self._connections = connections
        self._metadata = metadata or MetadataService(connections)
        self.setWindowTitle("MagicCat")
        self.resize(1200, 760)

        # 中央占位（M3 起接入 SQL 编辑器/结果网格）
        central = QWidget()
        layout = QVBoxLayout(central)
        hint = QLabel("选择左侧连接展开浏览数据库对象\nSQL 编辑器与数据网格将在后续里程碑接入")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)
        self.setCentralWidget(central)

        # 对象浏览器
        self.explorer = ObjectExplorer(self._connections, self._metadata)
        self.explorer.open_table_requested.connect(self._on_open_table)
        dock = QDockWidget("对象浏览器", self)
        dock.setWidget(self.explorer)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.explorer.load_profiles()

        self.statusBar().showMessage("就绪")
        self._build_actions()

    def _build_actions(self) -> None:
        menu = self.menuBar().addMenu("连接(&C)")
        act_add = menu.addAction("新增连接…")
        act_add.triggered.connect(self._add_connection)
        act_test = menu.addAction("测试连接…")
        act_test.triggered.connect(self._test_prompt)
        menu.addSeparator()
        act_exit = menu.addAction("退出")
        act_exit.triggered.connect(self.close)

        toolbar = self.addToolBar("连接")
        toolbar.addAction(act_add)

    # ---- 动作 ----
    def _add_connection(self) -> None:
        dialog = ConnectionEditDialog(self, groups=self._connections.groups)
        if dialog.exec():
            self._connections.add(dialog.profile())
            self.explorer.load_profiles()
            self.statusBar().showMessage("连接已保存", 3000)

    def _test_prompt(self) -> None:
        profiles = self._connections.profiles
        if not profiles:
            QMessageBox.information(self, "测试连接", "请先新增一个连接。")
            return
        from PySide6.QtWidgets import QInputDialog

        names = [p.display_name for p in profiles]
        name, ok = QInputDialog.getItem(self, "测试连接", "选择要测试的连接：", names, 0, False)
        if not ok:
            return
        profile = profiles[names.index(name)]
        self.statusBar().showMessage(f"正在测试「{profile.name}」…")
        run_async(
            lambda: self._connections.test(profile),
            lambda version: self.statusBar().showMessage(
                f"「{profile.name}」连接成功：{version}", 5000),
            lambda err: QMessageBox.warning(self, "测试连接", f"「{profile.name}」失败：\n{err}"))

    def _on_open_table(self, profile_id: str, schema: str, table: str) -> None:
        # M3/M4 将在此打开数据页；当前仅提示
        self.statusBar().showMessage(f"待接入数据页：{schema}.{table}", 5000)
