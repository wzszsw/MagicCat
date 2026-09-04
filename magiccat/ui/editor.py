"""SQL 编辑器组件（自研，设计方案 §5.2）：行号、语法高亮、自动补全。

不内嵌任何数据库逻辑：仅通过 text()/current_sql() 对外提供文本，
执行与结果展示由上层（MainWindow + QueryService）负责。
"""

from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QStandardItem,
    QStandardItemModel,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QWidget

from magiccat.services.sql_text import statement_at_cursor

# ---- MySQL 常用关键字（补全与高亮共用） ----
KEYWORDS = [
    "SELECT", "FROM", "WHERE", "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE",
    "CREATE", "ALTER", "DROP", "TABLE", "DATABASE", "SCHEMA", "INDEX", "VIEW", "TRIGGER",
    "PROCEDURE", "FUNCTION", "BEGIN", "END", "IF", "ELSE", "CASE", "WHEN", "THEN",
    "WHILE", "LOOP", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS", "ON",
    "AND", "OR", "NOT", "IN", "IS", "NULL", "LIKE", "BETWEEN", "EXISTS", "DISTINCT",
    "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "ALL", "AS", "ASC",
    "DESC", "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "UNIQUE", "CHECK", "DEFAULT",
    "AUTO_INCREMENT", "COMMENT", "ENGINE", "CHARSET", "COLLATE", "GRANT", "REVOKE",
    "SHOW", "DESCRIBE", "EXPLAIN", "USE", "TRUNCATE", "RENAME", "COMMIT", "ROLLBACK",
    "START", "TRANSACTION", "RETURN", "DECLARE", "CURSOR", "TINYINT", "SMALLINT",
    "MEDIUMINT", "INT", "INTEGER", "BIGINT", "DECIMAL", "FLOAT", "DOUBLE", "CHAR",
    "VARCHAR", "TEXT", "TINYTEXT", "MEDIUMTEXT", "LONGTEXT", "BLOB", "DATE", "TIME",
    "DATETIME", "TIMESTAMP", "YEAR", "JSON", "ENUM", "BOOLEAN",
]

_KEYWORD_ALTERNATION = "|".join(sorted(KEYWORDS, key=len, reverse=True))


def _rule(regex: str, color: str, bold: bool = False):
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    return re.compile(regex), fmt


class _MySqlHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        kw = rf"\b(?:{_KEYWORD_ALTERNATION})\b"
        self._line_rules = [
            _rule(r"\b\d+(?:\.\d+)?\b", "#1750EB"),
            _rule(kw, "#7D0A90", bold=True),
            _rule(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", "#067D17"),
            _rule(r"`(?:``|[^`])*`", "#0F4F8F"),
            _rule(r"--[^\r\n]*|#[^\r\n]*", "#8C8C8C"),
        ]
        self._cs = re.compile(r"/\*")
        self._ce = re.compile(r"\*/")
        self._fmt_comment = QTextCharFormat()
        self._fmt_comment.setForeground(QColor("#8C8C8C"))
        self._fmt_comment.setFontItalic(True)

    def highlightBlock(self, text: str) -> None:
        # 1) 行内规则（顺序即优先级：数字→关键字→字符串→反引号→行注释）
        for regex, fmt in self._line_rules:
            for m in regex.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        # 2) 块注释（覆盖行内规则，保证注释内不高亮关键字）
        self.setCurrentBlockState(0)
        start_index = 0
        if self.previousBlockState() != 1:
            m = self._cs.search(text)
            start_index = m.start() if m else -1
        while start_index >= 0:
            em = self._ce.search(text, start_index)
            if em is None:
                self.setCurrentBlockState(1)
                comment_length = len(text) - start_index
            else:
                comment_length = em.end() - start_index
            self.setFormat(start_index, comment_length, self._fmt_comment)
            m = self._cs.search(text, start_index + comment_length)
            start_index = m.start() if m else -1


class _LineNumberArea(QWidget):
    def __init__(self, editor: SqlEditorWidget) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#F0F0F0"))
        block = self._editor.firstVisibleBlock()
        top = round(self._editor.blockBoundingGeometry(block)
                    .translated(self._editor.contentOffset()).top())
        bottom = top + round(self._editor.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#808080"))
                painter.drawText(0, top, self.width() - 4,
                                 self._editor.fontMetrics().height(),
                                 Qt.AlignRight, str(block.blockNumber() + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self._editor.blockBoundingRect(block).height())


class SqlEditorWidget(QPlainTextEdit):
    """单标签 SQL 编辑器。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        font = QFont("Consolas")
        font.setPointSize(10)
        self.setFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

        self._highlighter = _MySqlHighlighter(self.document())
        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self._update_line_area_width()

        self._completer: QCompleter | None = None
        self.set_completion_words([])

    # ---- 行号 ----
    def line_number_area_width(self) -> int:
        digits = max(2, len(str(self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_area_width(self, *_args) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_area(self, rect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    # ---- 自动补全 ----
    def set_completion_words(self, words: list[str]) -> None:
        model = QStandardItemModel(self)
        for w in sorted(set(KEYWORDS) | set(words), key=str.lower):
            model.appendRow(QStandardItem(w))
        if self._completer is not None:
            self._completer.setModel(model)
            return
        self._completer = QCompleter(model, self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.activated.connect(self._insert_completion)

    def set_completion_data(self, data: dict) -> None:
        """上下文补全数据（{tables, columns}）：把表/视图名并入补全词表。"""
        names = [t.get("name") for t in data.get("tables", []) if t.get("name")]
        if names:
            self.set_completion_words(names)

    def _word_range(self) -> tuple[str, int]:
        cursor = self.textCursor()
        cursor.select(QTextCursor.WordUnderCursor)
        return cursor.selectedText(), cursor.selectionStart()

    def _insert_completion(self, completion: str) -> None:
        _prefix, start = self._word_range()
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.EndOfWord, QTextCursor.KeepAnchor)
        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def keyPressEvent(self, event) -> None:
        if (self._completer is not None and self._completer.popup().isVisible()
                and event.key() in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab, Qt.Key_Escape)):
            event.ignore()
            return
        super().keyPressEvent(event)
        ctrl = event.modifiers() & Qt.ControlModifier
        if ctrl and event.key() == Qt.Key_Space:
            self._complete_manual()

    def _complete_manual(self) -> None:
        if self._completer is None:
            return
        prefix, _start = self._word_range()
        self._completer.setCompletionPrefix(prefix)
        self._completer.popup().setCurrentIndex(
            self._completer.completionModel().index(0, 0))
        cr = self.cursorRect()
        cr.setWidth(self._completer.popup().sizeHintForColumn(0)
                    + self._completer.popup().verticalScrollBar().sizeHint().width())
        self._completer.complete(cr)

    # ---- 对外文本接口 ----
    def selected_text(self) -> str | None:
        """返回当前选中的可执行文本；没有非空选区时返回 None。"""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return None
        return cursor.selectedText().replace("\u2029", "\n").strip() or None

    def current_sql(self) -> str | None:
        """选中文本优先；否则光标所在语句。"""
        selected = self.selected_text()
        if selected is not None:
            return selected
        cursor = self.textCursor()
        return statement_at_cursor(self.toPlainText(), cursor.position())

    def has_selection(self) -> bool:
        """当前是否框选了非空文本。"""
        return self.textCursor().hasSelection()

    def all_text(self) -> str:
        return self.toPlainText()
