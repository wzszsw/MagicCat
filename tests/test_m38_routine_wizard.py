"""M38 测试：函数向导模板 + 创建 过程/函数。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_routine_templates_creatable(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="M38", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    meta = MetadataService(connection_service)
    win = MainWindow(connection_service, meta)
    qtbot.addWidget(win)
    win.show()
    suffix = int(time.time() * 1000)
    fname, pname = f"mc_m38_f_{suffix}", f"mc_m38_p_{suffix}"

    def routine_types() -> dict[str, str]:
        return {r["name"]: r["type"] for r in meta.routines(profile, "test")}

    try:
        # 函数
        win._open_routine_template(profile, "test", "FUNCTION", fname)
        editor = win._active_editor()
        text = editor.toPlainText()
        assert "CREATE FUNCTION" in text and "DELIMITER $$" in text
        res = q.execute(profile, text)
        assert all(r["kind"] == "update" for r in res)
        assert routine_types()[fname] == "FUNCTION"

        # 过程
        win._open_routine_template(profile, "test", "PROCEDURE", pname)
        text2 = win._active_editor().toPlainText()
        assert "CREATE PROCEDURE" in text2 and "DELIMITER $$" in text2
        assert all(r["kind"] == "update" for r in q.execute(profile, text2))
        assert routine_types()[pname] == "PROCEDURE"
    finally:
        q.execute(profile, f"DROP FUNCTION IF EXISTS `test`.`{fname}`")
        q.execute(profile, f"DROP PROCEDURE IF EXISTS `test`.`{pname}`")
        connection_service.close(profile.id)
