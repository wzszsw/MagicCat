"""SQL 收藏管理对话框：维护 名称+SQL 片段列表，可插入当前编辑器。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from magiccat.services.snippets import SnippetStore


class SnippetDialog(QDialog):
    def __init__(self, store: SnippetStore, insert_callback, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._insert_callback = insert_callback
        self.setWindowTitle("SQL 收藏")
        self.resize(720, 480)
        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)
        left = QVBoxLayout()
        left.addWidget(QLabel("收藏："))
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_select)
        left.addWidget(self.list_widget)
        splitter.addWidget(self._wrap(left))

        right = QVBoxLayout()
        self.sql_edit = QPlainTextEdit()
        self.sql_edit.setPlaceholderText("SQL 片段…")
        right.addWidget(self.sql_edit)
        splitter.addWidget(self._wrap(right))
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        bar = QHBoxLayout()
        btn_add = QPushButton("新增收藏")
        btn_update = QPushButton("更新当前")
        btn_delete = QPushButton("删除当前")
        btn_insert = QPushButton("插入到编辑器")
        for b in (btn_add, btn_update, btn_delete, btn_insert):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        root.addWidget(buttons)

        btn_add.clicked.connect(self._add)
        btn_update.clicked.connect(self._update_current)
        btn_delete.clicked.connect(self._delete_current)
        btn_insert.clicked.connect(self._insert_current)
        self._snippets: list[dict] = store.load()
        self._refresh()

    @staticmethod
    def _wrap(layout) -> object:
        from PySide6.QtWidgets import QWidget

        w = QWidget()
        w.setLayout(layout)
        return w

    def _refresh(self) -> None:
        self.list_widget.clear()
        for s in self._snippets:
            self.list_widget.addItem(s["name"])

    def _current(self) -> dict | None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._snippets):
            return self._snippets[row]
        return None

    def _on_select(self) -> None:
        s = self._current()
        self.sql_edit.setPlainText(s["sql"] if s else "")

    def _persist(self) -> None:
        self._store.save(self._snippets)

    def _add(self) -> None:
        name, ok = QInputDialog.getText(self, "新增收藏", "收藏名称：")
        if not ok or not name.strip():
            return
        sql = self.sql_edit.toPlainText().strip()
        if not sql:
            QMessageBox.information(self, "新增收藏", "SQL 内容为空。")
            return
        for s in self._snippets:
            if s["name"] == name.strip():
                QMessageBox.information(self, "新增收藏", "同名收藏已存在。")
                return
        self._snippets.append({"name": name.strip(), "sql": sql})
        self._persist()
        self._refresh()
        self.list_widget.setCurrentRow(len(self._snippets) - 1)

    def _update_current(self) -> None:
        s = self._current()
        if s is None:
            QMessageBox.information(self, "更新", "请先选择一条收藏。")
            return
        s["sql"] = self.sql_edit.toPlainText()
        self._persist()

    def _delete_current(self) -> None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._snippets):
            del self._snippets[row]
            self._persist()
            self._refresh()

    def _insert_current(self) -> None:
        s = self._current()
        if s is None:
            QMessageBox.information(self, "插入", "请先选择一条收藏。")
            return
        self._insert_callback(s["sql"])
        self.accept()
