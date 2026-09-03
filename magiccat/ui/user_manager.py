"""用户管理（M47）：用户表格 + 新建/编辑/删除 + 权限查看（对标 Navicat）。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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


class _AccountDialog(QDialog):
    """新建/编辑用户（密码）。kind: create|password"""

    def __init__(self, kind: str, parent=None, preset_user: str = "", preset_host: str = "") -> None:
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle("新建用户" if kind == "create" else "修改密码")
        self.setMinimumWidth(380)
        form = QFormLayout()
        self.user_edit = QLineEdit(preset_user)
        self.host_edit = QLineEdit(preset_host or "localhost")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        form.addRow("用户名：", self.user_edit)
        form.addRow("主机：", self.host_edit)
        form.addRow("密码：", self.pass_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        if kind != "create":
            self.user_edit.setEnabled(False)
            self.host_edit.setEnabled(False)

    def _accept(self) -> None:
        if not self.user_edit.text().strip() or not self.host_edit.text().strip():
            QMessageBox.information(self, "用户", "用户名与主机不能为空。")
            return
        self.accept()

    def values(self) -> tuple[str, str, str]:
        return (self.user_edit.text().strip(), self.host_edit.text().strip(),
                self.pass_edit.text())


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
        dlg = _AccountDialog("create", self)
        if not dlg.exec():
            return
        user, host, pwd = dlg.values()
        run_async(lambda: user_service.create_user(self._query, self.profile, user, host, pwd),
                  lambda _res: self._reload(),
                  lambda err: QMessageBox.critical(self, "新建用户", err))

    def _edit_user(self) -> None:
        sel = self._selected()
        if sel is None:
            QMessageBox.information(self, "编辑用户", "请先选择用户。")
            return
        dlg = _AccountDialog("password", self, preset_user=sel["user"],
                             preset_host=sel["host"])
        if not dlg.exec():
            return
        _user, _host, pwd = dlg.values()
        run_async(lambda: user_service.alter_password(self._query, self.profile,
                                                      sel["user"], sel["host"], pwd),
                  lambda _res: self._reload(),
                  lambda err: QMessageBox.critical(self, "修改密码", err))

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
