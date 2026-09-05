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
    QSpinBox,
)

from magiccat.services import user_service
from magiccat.services.connection_service import ConnectionService
from magiccat.services.query_service import QueryService
from magiccat.ui.job import run_async
from magiccat.ui.object_browse import ObjectBrowseView

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


class UserManagerWidget(ObjectBrowseView):
    tab_key = "user-manager"

    def __init__(self, profile, connections: ConnectionService, parent=None) -> None:
        super().__init__(parent)
        self.profile = profile
        self._connections = connections
        self._query = QueryService(connections)
        self._users: list[dict] = []
        self.configure(
            _COLUMNS,
            name_column=0,
            new_text="新建用户",
            open_text="编辑用户",
            delete_text="删除用户",
            keys=["name", "plugin", "ssl_type", "max_questions", "max_updates",
                  "max_connections", "max_user_connections", "super_priv"],
            icon_kind="user",
        )
        self.new_object.connect(self._new_user)
        self.refresh_requested.connect(self._reload)
        self.add_tool_button("显示权限", self._show_grants)
        self.status = QLabel("加载中…")
        self.layout().addWidget(self.status)
        self.set_profile(profile)

    def set_profile(self, profile) -> None:
        """切换对象页的当前连接；``None`` 表示尚未选择连接。"""
        self.profile = profile
        self._users = []
        self.table.clearContents()
        self.table.setRowCount(0)
        self.set_context_available(profile is not None)
        if profile is None:
            self.status.setText("请先选择连接")
            return
        self.status.setText("加载中…")
        self._reload()

    def clear(self) -> None:
        """清空当前用户领域，供对象页没有连接上下文时调用。"""
        self.set_profile(None)

    def _reload(self) -> None:
        if self.profile is None:
            return
        profile = self.profile
        run_async(lambda: user_service.list_users(self._query, profile),
                  lambda users: self._on_loaded(profile, users),
                  lambda err: self._on_error(profile, err))

    def _on_loaded(self, profile, users: list[dict]) -> None:
        if self.profile is None or self.profile.id != profile.id:
            return
        self._users = users
        rows = [{"name": f"{u['user']}@{u['host']}",
                 "plugin": u.get("plugin") or "",
                 "ssl_type": u.get("ssl_type") or "",
                 "max_questions": u.get("max_questions") or "",
                 "max_updates": u.get("max_updates") or "",
                 "max_connections": u.get("max_connections") or "",
                 "max_user_connections": u.get("max_user_connections") or "",
                 "super_priv": u.get("super_priv") or ""}
                for u in users]
        self.load(profile.id, rows)
        self.status.setText(f"共 {len(users)} 个用户")

    def _on_error(self, profile, err: str) -> None:
        if self.profile is not None and self.profile.id == profile.id:
            self.status.setText(f"加载失败：{err}")

    def _selected(self) -> dict | None:
        row = self._selected_row()
        if row < 0 or row >= len(self._users):
            return None
        return self._users[row]

    def _emit_open(self) -> None:
        self._edit_user()

    def _emit_delete(self) -> None:
        self._delete_user()

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
