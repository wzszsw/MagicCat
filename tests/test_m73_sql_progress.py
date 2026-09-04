"""M73 测试：SQL 进度对话框（转储/运行 SQL 文件共用的 Navicat 风格进度）。"""

from __future__ import annotations


def test_sql_progress_dialog_meta(qtbot):
    from magiccat.ui.sql_progress_dialog import SqlProgressDialog

    dlg = SqlProgressDialog()
    qtbot.addWidget(dlg)
    dlg.set_meta(server="127.0.0.1:5432", database="a", schema="public",
                 path="C:/tmp/out.sql")
    assert dlg._meta_labels["server"].text() == "127.0.0.1:5432"
    assert dlg._meta_labels["database"].text() == "a"
    assert dlg._meta_labels["schema"].text() == "public"
    assert dlg._meta_labels["path"].text() == "C:/tmp/out.sql"
    assert dlg.log_view.toPlainText() == ""
    assert not dlg.btn_open.isEnabled()


def test_sql_progress_dialog_progress_and_log(qtbot):
    from magiccat.ui.sql_progress_dialog import SqlProgressDialog

    dlg = SqlProgressDialog()
    qtbot.addWidget(dlg)
    dlg.set_meta(server="s", database="d", schema="p", path="x.sql")
    dlg._on_progress(1, 3, "[备份] 表 books：结构")
    assert dlg._meta_labels["done"].text() == "1"
    assert dlg.progress_bar.maximum() == 3
    assert dlg.progress_bar.value() == 1
    assert "[备份] 表 books：结构" in dlg.log_view.toPlainText()


def test_sql_progress_dialog_finished_sets_open(qtbot, tmp_path):
    from magiccat.ui.sql_progress_dialog import SqlProgressDialog

    out = tmp_path / "out.sql"
    out.write_text("-- x", encoding="utf-8")
    dlg = SqlProgressDialog()
    qtbot.addWidget(dlg)
    dlg.set_meta(server="s", database="d", schema="p", path=str(out))
    dlg._on_finished({"rows": 5, "errors": 0})
    assert dlg._meta_labels["rows"].text() == "5"
    assert dlg._meta_labels["errors"].text() == "0"
    assert dlg.btn_open.isEnabled()
