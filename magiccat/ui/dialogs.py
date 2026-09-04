"""连接配置编辑对话框——Navicat 式两步向导。

- 第 1 页：产品选择（图标网格 + 搜索），只列出已支持的产品
  （MySQL/MariaDB/PostgreSQL；Oracle/SQL Server 等未做，不列出）。
- 第 2 页：连接表单，按所选产品定制字段与默认值
  （MySQL：localhost/3306/root；PostgreSQL：localhost/5432/postgres）。
编辑已有连接时直接进入第 2 页，产品类型已锁定。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services.dialects import PROVIDERS, supported_keys


class _ProductCard(QToolButton):
    """产品卡片（图标在上、名称在下）。"""

    def __init__(self, key: str, display: str, parent=None) -> None:
        super().__init__(parent)
        from magiccat.ui.icons import icon

        self.key = key
        self.setText(display)
        self.setIcon(icon("profile", key))
        self.setIconSize(self.iconSize().expandedTo(self.sizeHint()))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setFixedSize(120, 96)


class ConnectionEditDialog(QDialog):
    """两步向导：产品选择 → 连接表单。"""

    def __init__(self, parent: QWidget | None = None,
                 profile: ConnectionProfile | None = None,
                 groups: list[str] | None = None) -> None:
        super().__init__(parent)
        self._editing = profile is not None
        self._profile_id = profile.id if profile is not None else None
        self._selected_key: str = profile.provider_key if profile is not None else "mysql"

        self.setWindowTitle("编辑连接" if profile else "新建连接")
        self.setMinimumWidth(560)
        self.setMinimumHeight(480)

        self._stack = QStackedWidget()
        self._build_product_page()
        self._build_form_page(profile, groups)
        self._stack.addWidget(self._product_page)
        self._stack.addWidget(self._form_page)

        bottom = QHBoxLayout()
        self.btn_back = QPushButton("上一步")
        self.btn_back.clicked.connect(self._go_back)
        self.btn_next = QPushButton("下一步")
        self.btn_next.clicked.connect(self._go_next)
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(self._test_connection)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.clicked.connect(self._validate_accept)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_back)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_test)
        bottom.addWidget(self.btn_next)
        bottom.addWidget(self.btn_ok)
        bottom.addWidget(self.btn_cancel)

        root = QVBoxLayout(self)
        root.addWidget(self._stack, 1)
        root.addLayout(bottom)

        # 编辑态：直接到第 2 页，锁定产品
        if self._editing:
            self._stack.setCurrentWidget(self._form_page)
            self._sync_buttons()
        else:
            self._stack.setCurrentWidget(self._product_page)
            self._sync_buttons()

    # ---- 第 1 页：产品选择 ----
    def _build_product_page(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        title = QLabel("选择数据库类型：")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        lay.addWidget(title)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索产品…")
        self._search_edit.textChanged.connect(self._apply_search)
        lay.addWidget(self._search_edit)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setSpacing(10)
        self._cards: dict[str, _ProductCard] = {}
        # 只列已支持产品（MySQL/MariaDB/PostgreSQL）
        for i, key in enumerate(supported_keys()):
            p = PROVIDERS[key]
            card = _ProductCard(key, p.display)
            card.clicked.connect(lambda _=False, k=key: self._select_product(k))
            self._cards[key] = card
            grid.addWidget(card, i // 3, i % 3)
        lay.addWidget(grid_host, 1)
        self._product_page = page

    def _apply_search(self, text: str) -> None:
        keyword = text.strip().lower()
        for card in self._cards.values():
            card.setVisible(keyword == "" or keyword in card.text().lower())

    def _select_product(self, key: str) -> None:
        self._selected_key = key
        self._go_next()

    # ---- 第 2 页：连接表单（按产品定制） ----
    def _build_form_page(self, profile: ConnectionProfile | None,
                         groups: list[str] | None = None) -> None:
        page = QWidget()
        form = QFormLayout(page)
        src = profile or ConnectionProfile(name="")

        self.name_edit = QLineEdit(src.name)
        self.type_combo = QComboBox()
        self.type_combo.setEnabled(not self._editing)  # 编辑态锁定产品
        for key in supported_keys():
            self.type_combo.addItem(PROVIDERS[key].display, key)
        self.type_combo.setCurrentIndex(self.type_combo.findData(src.provider_key))
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.host_edit = QLineEdit(src.host)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(src.port)
        self.user_edit = QLineEdit(src.username)
        self.pass_edit = QLineEdit(src.password)
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.db_edit = QLineEdit(src.database)
        self.db_edit.setPlaceholderText("可选：默认连接到的数据库")
        self.group_combo = QComboBox()
        for g in groups or []:
            self.group_combo.addItem(g)
        if src.group and self.group_combo.findText(src.group) < 0:
            self.group_combo.addItem(src.group)
        if self.group_combo.findText(DEFAULT_GROUP) < 0:
            self.group_combo.addItem(DEFAULT_GROUP)
        self.group_combo.setCurrentText(src.group or DEFAULT_GROUP)
        self.group_combo.setEditable(True)

        form.addRow("连接名称 *", self.name_edit)
        form.addRow("分组", self.group_combo)
        form.addRow("数据库类型", self.type_combo)
        form.addRow("主机", self.host_edit)
        form.addRow("端口", self.port_spin)
        form.addRow("用户名", self.user_edit)
        form.addRow("密码", self.pass_edit)
        form.addRow("数据库", self.db_edit)

        # 底部「测试连接」按钮在向导底栏，故这里仅放保存密码提示
        self._form_page = page
        # 应用产品默认值
        self._apply_defaults()

    def _on_type_changed(self) -> None:
        self._selected_key = self.type_combo.currentData() or "mysql"
        # 切换到新产品：采用该产品的默认 主机/端口/用户名
        self._apply_defaults(force_user=True)

    def _apply_defaults(self, force_user: bool = False) -> None:
        """按当前产品应用默认主机/端口/用户名。

        force_user=True 时强制覆盖用户名/端口（用于“刚选新产品”场景），
        否则仅当字段仍为默认/空白时才跟随，避免覆盖用户已手填的值。
        """
        key = self._selected_key
        defaults = {
            "mysql": ("localhost", 3306, "root"),
            "mariadb": ("localhost", 3306, "root"),
            "postgresql": ("localhost", 5432, "postgres"),
        }.get(key)
        if defaults:
            host, port, user = defaults
            if not self.host_edit.text().strip():
                self.host_edit.setText(host)
            # 端口仅在仍是默认端口之一、或强制应用时跟随
            if force_user or self.port_spin.value() in (0, 3306, 5432):
                self.port_spin.setValue(port)
            if force_user or not self.user_edit.text().strip():
                self.user_edit.setText(user)

    # ---- 导航 ----
    def _go_back(self) -> None:
        if not self._editing:
            self._stack.setCurrentWidget(self._product_page)
        self._sync_buttons()

    def _go_next(self) -> None:
        # 刚从产品页选中一个新产品：应用该产品的默认 主机/端口/用户名
        self._sync_type_combo()
        self._apply_defaults(force_user=True)
        self._stack.setCurrentWidget(self._form_page)
        self._sync_buttons()

    def _sync_type_combo(self) -> None:
        idx = self.type_combo.findData(self._selected_key)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

    def _sync_buttons(self) -> None:
        is_form = self._stack.currentWidget() is self._form_page
        self.btn_back.setVisible(not self._editing)
        self.btn_next.setVisible(not self._editing and not is_form)
        self.btn_ok.setVisible(is_form or self._editing)
        self.btn_test.setVisible(is_form or self._editing)

    def _test_connection(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from magiccat.services.connection_service import ConnectionService
        from magiccat.services.profile_store import ProfileStore

        try:
            prof = self.profile()
            ver = ConnectionService(ProfileStore.default()).test(prof)
            QMessageBox.information(self, "测试连接", f"连接成功：{ver}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "测试连接", f"连接失败：\n{exc}")

    def _validate_accept(self) -> None:
        if not self.name_edit.text().strip():
            self.name_edit.setFocus()
            self.name_edit.setPlaceholderText("名称不能为空")
            return
        self.accept()

    def profile(self) -> ConnectionProfile:
        base = ConnectionProfile(name=self.name_edit.text().strip())
        if self._profile_id is not None:
            base.id = self._profile_id
        base.group = self.group_combo.currentText().strip() or DEFAULT_GROUP
        base.provider_key = self.type_combo.currentData() or self._selected_key or "mysql"
        base.host = self.host_edit.text().strip() or "127.0.0.1"
        base.port = self.port_spin.value()
        base.username = self.user_edit.text().strip() or "root"
        base.password = self.pass_edit.text()
        base.database = self.db_edit.text().strip()
        return base
