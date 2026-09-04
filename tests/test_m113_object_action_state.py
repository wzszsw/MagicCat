"""M113 回归：对象页无连接上下文时操作按钮禁用。"""

from __future__ import annotations


def test_table_workspace_actions_follow_context_state(qtbot):
    from magiccat.ui.table_browse import TableBrowseView

    page = TableBrowseView()
    qtbot.addWidget(page)

    assert not page.btn_new.isEnabled()
    assert not page.btn_open.isEnabled()
    assert not page.btn_del.isEnabled()
    assert not page.btn_refresh.isEnabled()

    page.load_tables(
        "profile", "test",
        [{"name": "books", "type": "BASE TABLE", "engine": "",
          "rows": "", "comment": ""}],
    )
    assert page.btn_new.isEnabled()
    assert page.btn_refresh.isEnabled()
    assert not page.btn_open.isEnabled()
    assert not page.btn_del.isEnabled()
    page.table.selectRow(0)
    assert page.btn_open.isEnabled()
    assert page.btn_del.isEnabled()

    page.clear()
    assert not page.btn_new.isEnabled()
    assert not page.btn_refresh.isEnabled()
    assert not page.btn_open.isEnabled()
    assert not page.btn_del.isEnabled()
