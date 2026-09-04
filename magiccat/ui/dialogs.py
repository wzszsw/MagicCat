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
from magiccat.services.dialects import PROVIDERS


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
        self.type_combo = QComboBox()
        for key, p in PROVIDERS.items():
            self.type_combo.addItem(f"{p.display}", key)
        # 默认选中 Profile 的 provider_key（不支持时回退 mysql）
        type_idx = self.type_combo.findData(src.provider_key)
        if type_idx < 0:
            type_idx = self.type_combo.findData("mysql")
        self.type_combo.setCurrentIndex(type_idx)
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
        form.addRow("数据库类型", self.type_combo)
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

    def _on_type_changed(self) -> None:
        """随数据库类型调整默认端口/用户名（仅当用户尚未手动指定时才提示性的默认值）。"""
        key = self.type_combo.currentData()
        default_port = {"mysql": 3306, "mariadb": 3306}.get(key)
        default_user = {"postgresql": "postgres"}.get(key)
        if default_port and self.port_spin.value() in (3306, 5432):
            self.port_spin.setValue(default_port)
        # PostgreSQL 连接库默认为空（连默认库），不强制填
        if key == "postgresql" and not self.db_edit.text().strip():
            self.db_edit.setPlaceholderText("可选，默认连 postgres")
        if default_user and not self.user_edit.text().strip():
            self.user_edit.setText(default_user)

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
        base.provider_key = self.type_combo.currentData() or "mysql"
        base.host = self.host_edit.text().strip() or "127.0.0.1"
        base.port = self.port_spin.value()
        base.username = self.user_edit.text().strip() or "root"
        base.password = self.pass_edit.text()
        base.database = self.db_edit.text().strip()
        return base
