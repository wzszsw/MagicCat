"""用户管理（M49）：Navicat 风格账号表单（用户名/主机/插件/密码/过期策略）+ 表格操作。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from magiccat.services import user_service
from magiccat.services.connection_service import ConnectionService
from magiccat.services.query_service import QueryService
from magiccat.ui.grid import ResultTableModel
from magiccat.ui.job import run_async

_COLUMNS = ["名称", "插件", "SSL 类型", "每小时查询", "每小时更新",
            "每小时连接", "最大连接数", "超级用户"]
_PLUGINS = ["caching_sha2_password", "mysql_native_password", "sha256_password", "auth_socket"]


class UserEditDialog(QDialog):
    """编辑/新建用户（对标 Navicat 常规：用户名/主机/插件/密码/确认/密码过期策略）。"""

    def __init__(self, mode: str, parent=None, preset_user: str = "", preset_host: str = "",
                 preset_plugin: str = "") -> None:
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle("新建用户" if mode == "create" else "编辑用户")
        self.setMinimumWidth(420)
        form = QFormLayout(self)

        self.user_edit = QLineEdit(preset_user)
        self.host_edit = QLineEdit(preset_host or "localhost")
        self.plugin_combo = QComboBox()
        self.plugin_combo.addItems(_PLUGINS)
        if preset_plugin and self.plugin_combo.findText(preset_plugin) < 0:
            self.plugin_combo.addItem(preset_plugin)
        if preset_plugin:
            self.plugin_combo.setCurrentText(preset_plugin)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.Password)
        self.expire_combo = QComboBox()
        self.expire_combo.addItems(["DEFAULT", "NEVER", "INTERVAL"])
        self.expire_days = QSpinBox()
        self.expire_days.setRange(1, 3650)
        self.expire_days.setValue(90)
        self.expire_days.setEnabled(False)
        self.expire_combo.currentTextChanged.connect(
            lambda t: self.expire_days.setEnabled(t == "INTERVAL"))
        expire_row = QHBoxLayout()
        expire_row.addWidget(self.expire_combo)
        expire_row.addWidget(self.expire_days)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color: #555; font-family: Consolas;")

        form.addRow("用户名：", self.user_edit)
        form.addRow("主机：", self.host_edit)
        form.addRow("插件：", self.plugin_combo)
        form.addRow("密码：", self.pass_edit)
        form.addRow("确认密码：", self.confirm_edit)
        form.addRow("密码过期策略：", expire_row)
        form.addRow("SQL 预览：", self.preview_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if mode != "create":
            self.user_edit.setEnabled(False)
            self.host_edit.setEnabled(False)
        self.pass_edit.textChanged.connect(self._refresh_preview)
        self.confirm_edit.textChanged.connect(self._refresh_preview)
        self.plugin_combo.currentIndexChanged.connect(lambda _: self._refresh_preview())
        self.expire_combo.currentIndexChanged.connect(lambda _: self._refresh_preview())
        self.expire_days.valueChanged.connect(lambda _: self._refresh_preview())
        self._refresh_preview()

    def expire_value(self) -> str:
        text = self.expire_combo.currentText()
        if text == "INTERVAL":
            return f"INTERVAL {self.expire_days.value()} DAY"
        return text

    def _refreshed_members(self) -> dict:
        return {"user": self.user_edit.text().strip(),
                "host": self.host_edit.text().strip(),
                "plugin": self.plugin_combo.currentText(),
                "password": self.pass_edit.text(),
                "expire": self.expire_value()}

    def _refresh_preview(self) -> None:
        v = self._refreshed_members()
        if not v["user"]:
            self.preview_label.setText("")
            return
        ident = user_service._quote(v["user"], v["host"])
        masked_pwd = "***" if v["password"] else ""
        auth = user_service._auth_clause(masked_pwd, v["plugin"])
        exp = user_service._expire_clause(v["expire"])
        verb = "CREATE USER" if self.mode == "create" else "ALTER USER"
        self.preview_label.setText(f"{verb} {ident}{auth}{exp}")

    def _accept(self) -> None:
        v = self._refreshed_members()
        if not v["user"] or not v["host"]:
            QMessageBox.information(self, "用户", "用户名与主机不能为空。")
            return
        if v["password"] and v["password"] != self.confirm_edit.text():
            QMessageBox.warning(self, "用户", "两次输入密码不一致。")
            return
        self.accept()

    def values(self) -> dict:
        return self._refreshed_members()


class UserManagerWidget(QWidget):
    tab_key = "user-manager"

    def __init__(self, profile, connections: ConnectionService, parent=None) -> None:
        super().__init__(parent)
        self.profile = profile
        self._connections = connections
        self._query = QueryService(connections)
        self._users: list[dict] = []
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        for text, handler in (("新建用户", self._new_user), ("编辑用户", self._edit_user),
                              ("删除用户", self._delete_user), ("显示权限", self._show_grants),
                              ("刷新", self._reload)):
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            bar.addWidget(btn)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableView()
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        self.status = QLabel("加载中…")
        root.addWidget(self.status)
        self._reload()

    def _reload(self) -> None:
        run_async(lambda: user_service.list_users(self._query, self.profile),
                  self._on_loaded, lambda err: self.status.setText(f"加载失败：{err}"))

    def _on_loaded(self, users: list[dict]) -> None:
        self._users = users
        rows = []
        for u in users:
            rows.append([f"{u['user']}@{u['host']}", u.get("plugin") or "",
                         u.get("ssl_type") or "", u.get("max_questions") or "",
                         u.get("max_updates") or "", u.get("max_connections") or "",
                         u.get("max_user_connections") or "", u.get("super_priv") or ""])
        model = ResultTableModel(_COLUMNS, rows)
        self.table.setModel(model)
        self.status.setText(f"共 {len(users)} 个用户")

    def _selected(self) -> dict | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._users[rows[0].row()]

    def _new_user(self) -> None:
        dlg = UserEditDialog("create", self)
        if not dlg.exec():
            return
        v = dlg.values()
        run_async(lambda: user_service.create_user(
                self._query, self.profile, v["user"], v["host"], v["password"],
                plugin=v["plugin"], expire=v["expire"]),
                  lambda _res: self._reload(),
                  lambda err: QMessageBox.critical(self, "新建用户", err))

    def _edit_user(self) -> None:
        sel = self._selected()
        if sel is None:
            QMessageBox.information(self, "编辑用户", "请先选择用户。")
            return
        dlg = UserEditDialog("edit", self, preset_user=sel["user"], preset_host=sel["host"],
                             preset_plugin=sel.get("plugin") or "")
        if not dlg.exec():
            return
        v = dlg.values()
        run_async(lambda: user_service.alter_user(
                self._query, self.profile, v["user"], v["host"], password=v["password"],
                plugin=v["plugin"], expire=v["expire"]),
                  lambda _res: self._reload(),
                  lambda err: QMessageBox.critical(self, "编辑用户", err))

    def _delete_user(self) -> None:
        sel = self._selected()
        if sel is None:
            QMessageBox.information(self, "删除用户", "请先选择用户。")
            return
        if QMessageBox.question(
                self, "删除用户",
                f"确定删除用户 `{sel['user']}@{sel['host']}`？") != QMessageBox.Yes:
            return
        run_async(lambda: user_service.drop_user(self._query, self.profile,
                                                 sel["user"], sel["host"]),
                  lambda _res: self._reload(),
                  lambda err: QMessageBox.critical(self, "删除用户", err))

    def _show_grants(self) -> None:
        sel = self._selected()
        if sel is None:
            QMessageBox.information(self, "权限", "请先选择用户。")
            return
        run_async(lambda: user_service.show_grants(self._query, self.profile,
                                                   sel["user"], sel["host"]),
                  lambda text: QMessageBox.information(
                      self, f"权限 · {sel['user']}@{sel['host']}", text),
                  lambda err: QMessageBox.critical(self, "权限", err))
