"""连接配置编辑对话框——Navicat 式两步向导。

- 第 1 页：产品选择（图标网格 + 搜索），只列出已支持的产品
  （MySQL/MariaDB/PostgreSQL/GaussDB；Oracle/SQL Server 等未做，不列出）。
- 第 2 页：连接表单，按所选产品定制字段与默认值
  （MySQL：localhost/3306/root；PostgreSQL：localhost/5432/postgres；
  GaussDB：localhost/5432/gaussdb）。
编辑已有连接时直接进入第 2 页，产品类型已锁定。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from magiccat.models.profile import ConnectionProfile
from magiccat.services.dialects import (
    PROVIDERS,
    requires_initial_database,
    supported_keys,
)
from magiccat.services.settings import AppSettings
from magiccat.utils.errors import clean_java_error


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
                 groups: list[str] | None = None,
                 name_validator: Callable[[str, str, str | None], str] | None = None) -> None:
        super().__init__(parent)
        self._editing = profile is not None
        self._profile_id = profile.id if profile is not None else None
        self._name_validator = name_validator
        self._selected_key: str = profile.provider_key if profile is not None else "MYSQL"

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
        # 只列已支持产品（MySQL/MariaDB/PostgreSQL/GaussDB）
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
        spec = self._product_form_spec(self._selected_key)

        title = QLabel(spec["title"])
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        form.addRow("", title)
        self._form_title = title

        self.name_edit = QLineEdit(src.name)
        self.type_combo = QComboBox()
        # 产品已在第 1 页选择；保留控件供旧配置/自动化调用，但不在产品表单中重复显示。
        self.type_combo.setVisible(False)
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
        self.db_edit.setPlaceholderText(spec["database_placeholder"])
        form.addRow("连接名称 *", self.name_edit)
        self._type_label = QLabel("数据库类型")
        self._type_label.setVisible(False)
        form.addRow(self._type_label, self.type_combo)
        form.addRow("主机", self.host_edit)
        form.addRow("端口", self.port_spin)
        form.addRow("用户名", self.user_edit)
        form.addRow("密码", self.pass_edit)
        self._database_label = QLabel(spec["database_label"])
        form.addRow(self._database_label, self.db_edit)
        hint = QLabel(spec["hint"])
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; padding: 2px 0 6px 0;")
        form.addRow("", hint)
        self._product_hint = hint

        # 底部「测试连接」按钮在向导底栏，故这里仅放保存密码提示
        self._form_page = page
        self._sync_database_field()
        # 应用产品默认值
        self._apply_defaults()

    def _on_type_changed(self) -> None:
        self._selected_key = self.type_combo.currentData() or "MYSQL"
        # 切换到新产品：采用该产品的默认 主机/端口/用户名
        self._apply_defaults(force_user=True)
        spec = self._product_form_spec(self._selected_key)
        if hasattr(self, "_database_label"):
            self._form_title.setText(spec["title"])
            self._database_label.setText(spec["database_label"])
            self.db_edit.setPlaceholderText(spec["database_placeholder"])
            self._product_hint.setText(spec["hint"])
            self._sync_database_field()

    def _sync_database_field(self) -> None:
        """MySQL/MariaDB 不需要在连接配置中填写数据库。

        保留 ``db_edit`` 属性供 PostgreSQL/GaussDB 的必填初始化数据库使用，
        但 MySQL/MariaDB 的表单不展示该行，也不把历史值带回新的配置。
        """
        visible = requires_initial_database(self._selected_key)
        self._database_label.setVisible(visible)
        self.db_edit.setVisible(visible)
        if not visible:
            self.db_edit.clear()

    def _apply_defaults(self, force_user: bool = False) -> None:
        """按当前产品应用默认主机/端口/用户名。

        force_user=True 时强制覆盖用户名/端口（用于“刚选新产品”场景），
        否则仅当字段仍为默认/空白时才跟随，避免覆盖用户已手填的值。
        """
        key = self._selected_key
        defaults = {
            "MYSQL": ("localhost", 3306, "root", ""),
            "MARIADB": ("localhost", 3306, "root", ""),
            "PGSQL": ("localhost", 5432, "postgres", "postgres"),
            "GAUSSDB": ("localhost", 5432, "gaussdb", "postgres"),
        }.get(key)
        if defaults:
            host, port, user, database = defaults
            if not self.host_edit.text().strip():
                self.host_edit.setText(host)
            # 端口仅在仍是默认端口之一、或强制应用时跟随
            if force_user or self.port_spin.value() in (0, 3306, 5432):
                self.port_spin.setValue(port)
            if force_user or not self.user_edit.text().strip():
                self.user_edit.setText(user)
            if database and (force_user or not self.db_edit.text().strip()):
                self.db_edit.setText(database)

    @staticmethod
    def _product_form_spec(key: str) -> dict[str, str]:
        """每种产品独立的常规表单文案与字段语义。"""
        return {
            "MYSQL": {
                "title": "MySQL 连接",
                "database_label": "",
                "database_placeholder": "",
                "hint": "MySQL：连接后从服务器选择数据库。",
            },
            "MARIADB": {
                "title": "MariaDB 连接",
                "database_label": "",
                "database_placeholder": "",
                "hint": "MariaDB：连接后从服务器选择数据库。",
            },
            "PGSQL": {
                "title": "PostgreSQL 连接",
                "database_label": "初始化数据库 *",
                "database_placeholder": "必填，默认 postgres",
                "hint": "PostgreSQL：初始化数据库用于首次连接，连接后仍会列出其它数据库。",
            },
            "GAUSSDB": {
                "title": "GaussDB 连接",
                "database_label": "初始化数据库 *",
                "database_placeholder": "必填，默认 postgres",
                "hint": "GaussDB：初始化数据库用于首次连接；JDBC 驱动在“工具 → 环境”中指定。",
            },
        }.get(key, {
            "title": "数据库连接",
            "database_label": "数据库",
            "database_placeholder": "默认连接到的数据库",
            "hint": "",
        })

    # ---- 导航 ----
    def _go_back(self) -> None:
        if not self._editing:
            self._stack.setCurrentWidget(self._product_page)
        self._sync_buttons()

    def _go_next(self) -> None:
        # 刚从产品页选中一个新产品：应用该产品的默认 主机/端口/用户名
        self._sync_type_combo()
        self._form_title.setText(self._product_form_spec(self._selected_key)["title"])
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
        from magiccat.services.connection_service import ConnectionService
        from magiccat.services.profile_store import ProfileStore

        try:
            prof = self.profile()
            ver = ConnectionService(ProfileStore.default()).test(prof)
            QMessageBox.information(self, "测试连接", f"连接成功：{ver}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "测试连接", f"连接失败：\n{clean_java_error(exc)}")

    def _validate_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setFocus()
            self.name_edit.setPlaceholderText("名称不能为空")
            return
        key = self.type_combo.currentData() or self._selected_key
        if self._name_validator is not None:
            try:
                self._name_validator(name, key, self._profile_id)
            except ValueError as exc:
                QMessageBox.critical(self, "连接名称", str(exc))
                self.name_edit.setFocus()
                self.name_edit.selectAll()
                return
        if requires_initial_database(key) and not self.db_edit.text().strip():
            QMessageBox.warning(self, "初始数据库", "PostgreSQL/GaussDB 连接必须指定初始数据库。")
            self.db_edit.setFocus()
            return
        self.accept()

    def profile(self) -> ConnectionProfile:
        base = ConnectionProfile(name=self.name_edit.text().strip())
        if self._profile_id is not None:
            base.id = self._profile_id
        base.provider_key = self.type_combo.currentData() or self._selected_key or "MYSQL"
        base.host = self.host_edit.text().strip() or "127.0.0.1"
        base.port = self.port_spin.value()
        base.username = self.user_edit.text().strip() or "root"
        base.password = self.pass_edit.text()
        base.database = (self.db_edit.text().strip()
                         if requires_initial_database(base.provider_key) else "")
        return base


class EnvironmentDialog(QDialog):
    """Navicat 式“工具 → 环境”：配置不随软件分发的外部数据库驱动。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("环境")
        self.setMinimumWidth(620)
        settings = AppSettings.default()
        self._settings = settings

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.gaussdb_driver_edit = QLineEdit(
            str(settings.get("gaussdb_driver_jar", "") or ""))
        self.gaussdb_driver_edit.setPlaceholderText(
            "选择本机 gaussdbjdbc.jar；版权驱动不会被复制或打包")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_gaussdb_driver)
        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.addWidget(self.gaussdb_driver_edit, 1)
        row_lay.addWidget(browse)
        form.addRow("GaussDB JDBC 驱动 JAR", row)
        hint = QLabel("GaussDB 连接使用 jdbc:gaussdb://；请先指定华为提供的本地驱动 JAR。")
        hint.setWordWrap(True)
        form.addRow("说明", hint)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton("确定")
        ok.clicked.connect(self._save)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def _browse_gaussdb_driver(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 GaussDB JDBC 驱动", self.gaussdb_driver_edit.text(),
            "JAR 文件 (*.jar)")
        if path:
            self.gaussdb_driver_edit.setText(path)

    def _save(self) -> None:
        path = self.gaussdb_driver_edit.text().strip()
        if path and not Path(path).is_file():
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "环境", f"驱动 JAR 不存在：{path}")
            return
        self._settings.set("gaussdb_driver_jar", path)
        self.accept()
