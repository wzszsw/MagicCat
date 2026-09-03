"""函数向导（对标 Navicat：选择例程类型 + 名称）。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
)


class RoutineWizardDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("函数 向导")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("请选择你要创建的例程类型"))

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例程名称（如 get_user）")
        self.radio_proc = QRadioButton("过程")
        self.radio_func = QRadioButton("函数")
        self.radio_proc.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.radio_proc)
        group.addButton(self.radio_func)
        form.addRow("名称：", self.name_edit)
        form.addRow("", self.radio_proc)
        form.addRow("", self.radio_func)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _accept(self) -> None:
        if not self.name_edit.text().strip():
            self.name_edit.setFocus()
            self.name_edit.setPlaceholderText("名称不能为空")
            return
        self.accept()

    def kind(self) -> str:
        return "PROCEDURE" if self.radio_proc.isChecked() else "FUNCTION"

    def name(self) -> str:
        return self.name_edit.text().strip()
