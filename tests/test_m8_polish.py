"""M8 打磨测试：SQL 收藏存取 / 结果网格复制。"""

from __future__ import annotations

from magiccat.services.snippets import SnippetStore


def test_snippet_store_roundtrip(tmp_path):
    store = SnippetStore(tmp_path)
    assert store.load() == []
    store.save([{"name": "常用查询", "sql": "SELECT * FROM users WHERE id = ?"}])
    reloaded = SnippetStore(tmp_path).load()
    assert reloaded == [{"name": "常用查询", "sql": "SELECT * FROM users WHERE id = ?"}]


def test_result_view_copy(qtbot):
    from PySide6.QtWidgets import QApplication

    from magiccat.ui.grid import ResultTableModel, ResultView

    model = ResultTableModel(["id", "name"], [["1", "奥力给"], ["2", None], ["3", ""]])
    view = ResultView()
    qtbot.addWidget(view)
    view.setModel(model)

    # 无选中 → 整页复制（带表头）
    text = view.copy_selection(include_header=True)
    lines = text.splitlines()
    assert lines[0] == "id\tname"
    assert lines[1] == "1\t奥力给"
    assert lines[2] == "2\tNULL"
    assert lines[3] == "3\t"
    assert QApplication.clipboard().text() == text

    # 选中第一行 → 仅该行，无表头
    view.selectRow(0)
    text2 = view.copy_selection(include_header=False)
    assert text2 == "1\t奥力给"
