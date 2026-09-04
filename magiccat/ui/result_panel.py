"""结果面板（M3）：多结果标签 + 消息日志。

执行一段 SQL（可能含多条语句）后 show_results(results) 会：
- 每条查询 → 独立结果标签（表格 + 行数/耗时标注）
- 更新/错误 → 追加到“消息”日志
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QPlainTextEdit, QSplitter, QTabWidget, QWidget

from magiccat.ui.grid import ResultTableModel, ResultView


def _tab_title(result: dict) -> str:
    sql = " ".join(result.get("sql", "").split())[:24]
    if result.get("kind") == "query":
        return f"结果 · {len(result.get('rows', []))} 行 · {sql}"
    return sql or "结果"


class ResultPanel(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._splitter_sized = False
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        # 颜色交给应用主题：固定深色会让浅色主题下的消息区与 Navicat 观感不一致。
        self._log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.addTab(self._log, "消息")
        self._result_tab_indexes: list[int] = []

    def showEvent(self, event: QShowEvent) -> None:
        """面板从隐藏状态出现时，把它放回查询区底部而不是占满整个工作区。

        查询工作区用 ``QSplitter`` 承载编辑器和结果面板。隐藏的 splitter 子项
        初始尺寸通常为 0；直接 ``setVisible(True)`` 时，Qt 在部分平台会把剩余
        高度全部分给刚显示的子项。延迟到布局完成后显式设置一次尺寸即可避免
        该平台差异，同时不会干扰用户之后手动拖动分隔条。
        """
        super().showEvent(event)
        # 等父窗口完成这一轮布局后再取 splitter 高度；在 showEvent 当下读取
        # 到的几何值在高 DPI/不同窗口管理器下可能还是旧值，进而把面板撑满。
        if not self._splitter_sized:
            QTimer.singleShot(60, self._restore_splitter_size)

    def _restore_splitter_size(self) -> None:
        splitter = self.parentWidget()
        while splitter is not None and not isinstance(splitter, QSplitter):
            splitter = splitter.parentWidget()
        if splitter is None:
            return
        if self._splitter_sized:
            return
        total = splitter.height()
        if total <= 0:
            # 结果面板可能在父窗口首次布局前显示，再尝试一次即可。
            QTimer.singleShot(30, self._restore_splitter_size)
            return

        # Navicat 的消息区约占查询区底部三分之一；比例随窗口大小变化，
        # 避免在大屏上被固定像素上限压得过小。
        panel_height = max(140, round(total * 0.36))
        editor_height = total - panel_height
        if editor_height < 120:
            editor_height = max(1, total - 140)
            panel_height = total - editor_height
        splitter.setSizes([editor_height, panel_height])
        self._splitter_sized = True

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
