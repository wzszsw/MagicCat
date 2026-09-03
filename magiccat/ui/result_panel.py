"""结果面板（M3）：多结果标签 + 消息日志。

执行一段 SQL（可能含多条语句）后 show_results(results) 会：
- 每条查询 → 独立结果标签（表格 + 行数/耗时标注）
- 更新/错误 → 追加到“消息”日志
"""

from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit, QTabWidget, QWidget

from magiccat.ui.grid import ResultTableModel, ResultView


def _tab_title(result: dict) -> str:
    sql = " ".join(result.get("sql", "").split())[:24]
    if result.get("kind") == "query":
        return f"结果 · {len(result.get('rows', []))} 行 · {sql}"
    return sql or "结果"


class ResultPanel(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        self._log.setStyleSheet("QPlainTextEdit { background: #1E1E1E; color: #D4D4D4; }")
        self.addTab(self._log, "消息")
        self._result_tab_indexes: list[int] = []

    def append_message(self, text: str) -> None:
        self.setVisible(True)  # Navicat：消息窗默认隐藏，有消息自动出现
        self._log.appendPlainText(text)
        if not self._result_tab_indexes:
            self.setCurrentWidget(self._log)

    def clear_results(self) -> None:
        for index in sorted(self._result_tab_indexes, reverse=True):
            self.removeTab(index)
        self._result_tab_indexes = []

    def show_results(self, results: list[dict]) -> None:
        self.setVisible(True)
        self.clear_results()
        query_count = 0
        for result in results:
            kind = result.get("kind")
            if kind == "query":
                query_count += 1
                model = ResultTableModel(result.get("columns", []), result.get("rows", []))
                view = ResultView()
                view.setModel(model)
                title = _tab_title(result)
                if result.get("truncated"):
                    title += "（已截断）"
                self.addTab(view, title)
                self._result_tab_indexes.append(self.count() - 1)
                self.append_message(
                    f"[OK] {len(result['rows'])} 行 · {result['time_ms']} ms"
                    + ("（截断）" if result.get("truncated") else "")
                    + f"  <- {result['sql']}")
            elif kind == "update":
                self.append_message(
                    f"[OK] 影响 {result['affected']} 行 · {result['time_ms']} ms"
                    f"  <- {result['sql']}")
            elif kind == "error":
                self.append_message(
                    f"[错误] {result.get('message')}  <- {result['sql']}")
        if self._result_tab_indexes:
            self.setCurrentIndex(self._result_tab_indexes[0])
