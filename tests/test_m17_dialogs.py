"""M17 测试：向导/对话框真实构建与联动（offscreen，不触发阻塞式 exec/文件对话框）。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def _profile(mysql_env: dict) -> ConnectionProfile:
    return ConnectionProfile(name="M17", group=DEFAULT_GROUP,
                             host=mysql_env["host"], port=mysql_env["port"],
                             username=mysql_env["user"], password=mysql_env["password"])


def test_import_csv_dialog_linking(qtbot, mysql_env, connection_service):
    """导入向导：选连接 → 库/表下拉自动填充（元数据联动）。"""
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.transfer_dialogs import ImportCsvDialog

    profile = _profile(mysql_env)
    connection_service.add(profile)
    dialog = ImportCsvDialog(connection_service, MetadataService(connection_service))
    qtbot.addWidget(dialog)
    # __init__ 已填充连接；触发库联动
    assert dialog.profile_combo.count() >= 1
    assert dialog.schema_combo.count() >= 1, "应已同步加载库列表"
    assert "test" in [dialog.schema_combo.itemText(i) for i in range(dialog.schema_combo.count())]
    dialog.schema_combo.setCurrentText("test")
    assert dialog.table_combo.count() >= 0 and dialog.table_combo.isEnabled()


def test_copy_table_dialog_linking(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.transfer_dialogs import CopyTableDialog

    profile = _profile(mysql_env)
    connection_service.add(profile)
    dialog = CopyTableDialog(connection_service, MetadataService(connection_service))
    qtbot.addWidget(dialog)
    assert dialog.src_schema_combo.count() >= 1
    assert dialog.dst_schema_combo.count() == dialog.src_schema_combo.count()
    dialog.src_schema_combo.setCurrentText("test")
    assert dialog.src_table_combo.isEnabled()
    assert dialog.dst_table_edit.text() == ""  # 预填逻辑在开始复制时回退源表名


def test_snippet_dialog_shows_saved(qtbot, tmp_path):
    from magiccat.services.snippets import SnippetStore
    from magiccat.ui.snippet_dialog import SnippetDialog

    store = SnippetStore(tmp_path)
    store.save([{"name": "常用", "sql": "SELECT 1"}])
    inserted: list[str] = []
    dialog = SnippetDialog(store, inserted.append)
    qtbot.addWidget(dialog)
    assert dialog.list_widget.count() == 1
    dialog.list_widget.setCurrentRow(0)
    assert dialog.sql_edit.toPlainText() == "SELECT 1"
    dialog._insert_current()
    assert inserted == ["SELECT 1"]
