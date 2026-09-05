"""序列 新建/编辑/设计 对话框（对标 Navicat「其它」→ 序列的“常规”分组；PostgreSQL）。

- 常规分组：所有者 / 递增值 / 当前值 / 开始值 / 最小 / 最大 / 缓存 / 循环。
- SQL 预览：实时生成 CREATE SEQUENCE / ALTER SEQUENCE 语句（PostgreSQL 方言）。
- 新建模式：填写后生成 CREATE SEQUENCE；编辑模式：取现有值 + 生成 ALTER 片段。

此页仅做“常规”核心字段；“添加所有者 / 由表拥有 / 由列拥有”等归属关联字段暂不做。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

_DEFAULT_MAX = "9223372036854775807"


def _quote_identifier(value: str) -> str:
    """引用 PostgreSQL 标识符，避免所有者/对象名中的双引号破坏 SQL。"""
    return '"' + value.replace('"', '""') + '"'


class SequenceDialog(QDialog):
    """序列编辑对话框。mode: create | edit。"""

    def __init__(self, schema: str, name: str = "", mode: str = "create",
                 data: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.schema = schema
        self.name = name
        self.mode = mode
        self.data = data or {}
        self._original_owner = str(self.data.get("owner") or "").strip()
        self.setWindowTitle(("新建序列" if mode == "create" else "设计序列")
                            + f" · {schema}.{name or ''}")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # 常规分组
        common = QWidget()
        form = QFormLayout(common)
        self.owner_edit = QLineEdit(self.data.get("owner", ""))
        self.owner_edit.setPlaceholderText("如 postgres")
        self.increment_spin = QSpinBox()
        self.increment_spin.setRange(-2147483648, 2147483647)
        self.increment_spin.setValue(int(self.data.get("increment") or 1))
        self.current_edit = QLineEdit(str(self.data.get("last_value") or ""))
        self.current_edit.setPlaceholderText("当前值（可空）")
        self.start_edit = QLineEdit(str(self.data.get("start_value") or "1"))
        self.min_edit = QLineEdit(str(self.data.get("min_value") or "1"))
        self.max_edit = QLineEdit(str(self.data.get("max_value") or _DEFAULT_MAX))
        self.cache_spin = QSpinBox()
        self.cache_spin.setRange(1, 2147483647)
        self.cache_spin.setValue(int(self.data.get("cache") or 1))
        self.cycle_check = QCheckBox("循环")
        self.cycle_check.setChecked(str(self.data.get("cycle", "")).lower() in ("true", "t", "1"))

        form.addRow("所有者:", self.owner_edit)
        form.addRow("递增值:", self.increment_spin)
        form.addRow("当前的值:", self.current_edit)
        form.addRow("开始值:", self.start_edit)
        form.addRow("最小:", self.min_edit)
        form.addRow("最大:", self.max_edit)
        form.addRow("缓存:", self.cache_spin)
        form.addRow("", self.cycle_check)
        tabs.addTab(common, "常规")

        # SQL 预览
        sql_tab = QWidget()
        sql_lay = QVBoxLayout(sql_tab)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        sql_lay.addWidget(self.preview)
        tabs.addTab(sql_tab, "SQL 预览")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # 字段变化即刷新 SQL 预览
        self.owner_edit.textChanged.connect(self._refresh_preview)
        self.increment_spin.valueChanged.connect(self._refresh_preview)
        self.current_edit.textChanged.connect(self._refresh_preview)
        self.start_edit.textChanged.connect(self._refresh_preview)
        self.min_edit.textChanged.connect(self._refresh_preview)
        self.max_edit.textChanged.connect(self._refresh_preview)
        self.cache_spin.valueChanged.connect(self._refresh_preview)
        self.cycle_check.toggled.connect(self._refresh_preview)
        self._refresh_preview()

    # ---- SQL 生成 ----
    def sql(self) -> str:
        q = f"{_quote_identifier(self.schema)}.{_quote_identifier(self.name)}"
        if self.mode == "create":
            parts = [f"CREATE SEQUENCE {q}",
                     f"    INCREMENT BY {self.increment_spin.value()}",
                     f"    MINVALUE {self.min_edit.text().strip() or '1'}",
                     f"    MAXVALUE {self.max_edit.text().strip() or _DEFAULT_MAX}",
                     f"    START WITH {self.start_edit.text().strip() or '1'}",
                     f"    CACHE {self.cache_spin.value()}"]
            if self.cycle_check.isChecked():
                parts.append("    CYCLE")
            return "\n".join(parts) + ";"
        # edit：ALTER SEQUENCE；当前值用 RESTART WITH 才会真正写回序列。
        parts = [f"ALTER SEQUENCE {q}",
                 f"    INCREMENT BY {self.increment_spin.value()}",
                 f"    START WITH {self.start_edit.text().strip() or '1'}",
                 f"    MINVALUE {self.min_edit.text().strip() or '1'}",
                 f"    MAXVALUE {self.max_edit.text().strip() or _DEFAULT_MAX}",
                 f"    CACHE {self.cache_spin.value()}"]
        current = self.current_edit.text().strip()
        if current:
            parts.append(f"    RESTART WITH {current}")
        if self.cycle_check.isChecked():
            parts.append("    CYCLE")
        else:
            parts.append("    NO CYCLE")
        statements = ["\n".join(parts) + ";"]
        owner = self.owner_edit.text().strip()
        if owner and owner != self._original_owner:
            statements.append(f"ALTER SEQUENCE {q} OWNER TO {_quote_identifier(owner)};")
        return "\n".join(statements)

    def _refresh_preview(self) -> None:
        self.preview.setPlainText(self.sql())

    # ---- 结果 ----
    def values(self) -> dict:
        return {
            "owner": self.owner_edit.text().strip(),
            "increment": self.increment_spin.value(),
            "start_value": self.start_edit.text().strip() or "1",
            "min_value": self.min_edit.text().strip() or "1",
            "max_value": self.max_edit.text().strip() or _DEFAULT_MAX,
            "cache": self.cache_spin.value(),
            "cycle": self.cycle_check.isChecked(),
            "last_value": self.current_edit.text().strip(),
        }
