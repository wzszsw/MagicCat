"""M130 回归：左侧对象树的表节点暂不展开列。"""

from __future__ import annotations

from PySide6.QtWidgets import QTreeWidgetItem


def test_table_leaf_does_not_offer_column_expansion(qtbot) -> None:
    from magiccat.ui.object_explorer import ObjectExplorer

    explorer = ObjectExplorer(None, None)
    qtbot.addWidget(explorer)

    leaf = explorer._category_leaf(
        {"name": "books", "type": "BASE TABLE"}, "tables", "test"
    )

    assert leaf.childCount() == 0
    assert leaf.childIndicatorPolicy() == QTreeWidgetItem.DontShowIndicator


def test_table_expansion_handler_does_not_load_columns(qtbot, monkeypatch) -> None:
    from magiccat.ui.object_explorer import ObjectExplorer

    explorer = ObjectExplorer(None, None)
    qtbot.addWidget(explorer)
    leaf = explorer._category_leaf(
        {"name": "books", "type": "BASE TABLE"}, "tables", "test"
    )
    calls = []
    monkeypatch.setattr(explorer, "_load_columns", lambda item: calls.append(item))

    explorer._on_expanded(leaf)

    assert calls == []
