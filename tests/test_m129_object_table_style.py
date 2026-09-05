"""M129 回归：对象列表表格采用 Navicat 式无边框平面样式。"""

from __future__ import annotations


def test_object_browse_table_is_borderless(qtbot):
    from PySide6.QtWidgets import QFrame

    from magiccat.ui.table_browse import TableBrowseView

    view = TableBrowseView()
    qtbot.addWidget(view)

    assert view.table.objectName() == "objectBrowseTable"
    assert view.table.frameShape() == QFrame.NoFrame
    assert view.table.lineWidth() == 0
    assert not view.table.showGrid()
    assert not view.table.alternatingRowColors()
    assert view.table.verticalHeader().defaultSectionSize() == 24
    assert "border: none" in view.table.styleSheet()
    assert "QTableWidget::item:selected" in view.table.styleSheet()
    assert "background-color: #cfe8ff" in view.table.styleSheet()
    assert "color: #1f2937" in view.table.styleSheet()
