"""主题（QSS）。浅色使用 Qt 默认；深色为精简 QSS 调色板。"""

from __future__ import annotations

DARK_QSS = """
* { color: #D4D4D4; }
QMainWindow, QDialog, QWidget { background-color: #2B2D30; }
QMenuBar { background-color: #333537; }
QMenuBar::item:selected, QMenu::item:selected { background-color: #3E4043; }
QToolBar { background-color: #333537; border: none; spacing: 4px; }
QStatusBar { background-color: #333537; }
QScrollArea, QScrollArea > QWidget > QWidget { background-color: transparent; }
QScrollArea QWidget#frmBody { background-color: #2B2D30; }
QTreeWidget, QTableView, QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox {
    background-color: #1E1F22; border: 1px solid #44464A; }
QHeaderView::section { background-color: #333537; border: none; padding: 4px; }
QTabWidget::pane { border: 1px solid #44464A; }
QTabBar::tab { background: #333537; padding: 5px 12px; }
QTabBar::tab:selected { background: #1E1F22; }
QPushButton { background-color: #3E4043; border: 1px solid #55585D; padding: 4px 10px; }
QPushButton:hover { background-color: #4A4D52; }
QPushButton:disabled { color: #777; }
QProgressBar { background-color: #1E1F22; border: 1px solid #44464A; text-align: center; }
QProgressBar::chunk { background-color: #4E9A5A; }
QToolTip { background-color: #3E4043; color: #D4D4D4; }
"""


def apply_theme(widget, theme: str) -> None:
    """theme: light|dark。传入顶层窗口即可对整个 widget 树生效。"""
    widget.setStyleSheet(DARK_QSS if theme == "dark" else "")
