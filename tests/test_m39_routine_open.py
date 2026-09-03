"""M39 测试：双击“函数”节点打开其定义 SQL。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_open_routine_sql_editor(qtbot, mysql_env, connection_service):
    from magiccat.services.ddl_service import DdlService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="M39", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    meta = MetadataService(connection_service)
    win = MainWindow(connection_service, meta)
    qtbot.addWidget(win)
    win.show()
    name = f"mc_m39_f_{int(time.time() * 1000)}"
    try:
        q.execute(profile, (
            f"CREATE FUNCTION `test`.`{name}`() RETURNS INT "
            "DETERMINISTIC READS SQL DATA RETURN 7"))
        sql_text = DdlService(connection_service).show_create_routine(
            profile, "test", name, "FUNCTION")
        assert "CREATE" in sql_text and "FUNCTION" in sql_text.upper()

        win._open_routine_sql(profile.id, name, sql_text)
        editor = win._active_editor()
        assert "CREATE" in editor.toPlainText()
        title = win.editor_tabs.tabText(win.editor_tabs.indexOf(editor))
        assert title == name + "（函数）"
    finally:
        q.execute(profile, f"DROP FUNCTION IF EXISTS `test`.`{name}`")
        connection_service.close(profile.id)
