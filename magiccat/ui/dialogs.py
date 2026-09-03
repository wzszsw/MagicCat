"""连接配置编辑对话框（新增/编辑连接）。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


class ConnectionEditDialog(QDialog):
    def __init__(self, parent: QWidget | None = None,
                 profile: ConnectionProfile | None = None,
                 groups: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑连接" if profile else "新增连接")
        self.setMinimumWidth(420)

        self._editing = profile is not None
        self._profile_id = profile.id if profile is not None else None
        src = profile or ConnectionProfile(name="")

        form = QFormLayout()
        self.name_edit = QLineEdit(src.name)
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
        for g in (groups or []):
            self.group_combo.addItem(g)
        if src.group and self.group_combo.findText(src.group) < 0:
            self.group_combo.addItem(src.group)
        if self.group_combo.findText(DEFAULT_GROUP) < 0:
            self.group_combo.addItem(DEFAULT_GROUP)
        self.group_combo.setCurrentText(src.group or DEFAULT_GROUP)
        self.group_combo.setEditable(True)

        form.addRow("名称 *", self.name_edit)
        form.addRow("分组", self.group_combo)
        form.addRow("主机", self.host_edit)
        form.addRow("端口", self.port_spin)
        form.addRow("用户名", self.user_edit)
        form.addRow("密码", self.pass_edit)
        form.addRow("数据库", self.db_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

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
        base.host = self.host_edit.text().strip() or "127.0.0.1"
        base.port = self.port_spin.value()
        base.username = self.user_edit.text().strip() or "root"
        base.password = self.pass_edit.text()
        base.database = self.db_edit.text().strip()
        return base
