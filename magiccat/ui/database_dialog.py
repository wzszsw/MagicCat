"""编辑数据库（M41）：查看/修改字符集与排序规则（ALTER DATABASE）。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from magiccat.services.connection_service import ConnectionService
from magiccat.services.query_service import QueryService


def _columns_zip(result: dict) -> list[dict]:
    cols = result.get("columns", [])
    return [dict(zip(cols, row)) for row in result.get("rows", [])]


class EditDatabaseDialog(QDialog):
    def __init__(self, profile, schema: str, connections: ConnectionService,
                 parent=None) -> None:
        super().__init__(parent)
        self._profile = profile
        self._schema = schema
        self._query = QueryService(connections)
        self.setWindowTitle(f"编辑数据库 · {schema}（{profile.name}）")
        self.setMinimumWidth(400)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"数据库：{schema}"))

        form = QFormLayout()
        self.charset_combo = QComboBox()
        self.collation_combo = QComboBox()
        form.addRow("字符集：", self.charset_combo)
        form.addRow("排序规则：", self.collation_combo)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._buttons = buttons
        self.charset_combo.currentIndexChanged.connect(self._on_charset_changed)
        self._load()

    def _on_charset_changed(self) -> None:
        charset = self.charset_combo.currentText()
        if charset:
            self._fill_collations(charset)

    def _current_info(self) -> dict:
        res = self._query.execute(self._profile, (
            "SELECT DEFAULT_CHARACTER_SET_NAME AS cs, DEFAULT_COLLATION_NAME AS cl "
            f"FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '{self._schema}'"))[0]
        rows = res.get("rows", [])
        return {"cs": rows[0][0] if rows else "", "cl": rows[0][1] if rows else ""}

    def _load(self) -> None:
        try:
            info = self._current_info()
            cs_res = self._query.execute(self._profile, "SHOW CHARACTER SET")[0]
            charset_names = [r["Charset"] for r in _columns_zip(cs_res)]
            self.charset_combo.addItems(charset_names)
            current_cs = info["cs"]
            idx = self.charset_combo.findText(current_cs)
            if idx >= 0:
                self.charset_combo.setCurrentIndex(idx)
            self._fill_collations(current_cs, info["cl"])
        except Exception as exc:  # noqa: BLE001
            self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            QMessageBox.critical(self, "编辑数据库", f"读取元数据失败：{exc}")

    def _fill_collations(self, charset: str, current: str | None = None) -> None:
        self.collation_combo.clear()
        res = self._query.execute(self._profile,
                                  f"SHOW COLLATION WHERE Charset = '{charset}'")[0]
        for r in _columns_zip(res):
            self.collation_combo.addItem(r["Collation"])
        if current:
            idx = self.collation_combo.findText(current)
            if idx >= 0:
                self.collation_combo.setCurrentIndex(idx)

    def _accept(self) -> None:
        charset = self.charset_combo.currentText()
        collation = self.collation_combo.currentText()
        if not charset or not collation:
            return
        if QMessageBox.question(
                self, "编辑数据库",
                f"ALTER DATABASE `{self._schema}` CHARACTER SET {charset} "
                f"COLLATE {collation}\n确定应用？") != QMessageBox.Yes:
            return
        results = self._query.execute(
            self._profile,
            f"ALTER DATABASE `{self._schema}` CHARACTER SET {charset} COLLATE {collation}")
        errors = [r for r in results if r.get("kind") == "error"]
        if errors:
            QMessageBox.critical(self, "编辑数据库", errors[0]["message"])
            return
        QMessageBox.information(self, "编辑数据库", "已更新字符集/排序规则。")
        self.accept()
