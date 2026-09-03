"""M41 测试：编辑数据库（字符集/排序规则）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def _schema_cs_cl(q, profile, db: str) -> tuple[str, str]:
    res = q.execute(profile, (
        "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
        f"FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '{db}'"))[0]
    row = res["rows"][0]
    return row[0], row[1]


def test_edit_database_dialog(qtbot, mysql_env, connection_service):
    from magiccat.services.query_service import QueryService
    from magiccat.ui.database_dialog import EditDatabaseDialog

    profile = ConnectionProfile(name="M41", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    db = f"mc_m41_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE DATABASE `{db}`")
        dialog = EditDatabaseDialog(profile, db, connection_service)
        qtbot.addWidget(dialog)
        charsets = [dialog.charset_combo.itemText(i)
                    for i in range(dialog.charset_combo.count())]
        assert "utf8mb4" in charsets and "utf8mb3" in charsets
        # 字符集切换后排序规则列表联动
        dialog.charset_combo.setCurrentText("utf8mb3")
        collations = [dialog.collation_combo.itemText(i)
                      for i in range(dialog.collation_combo.count())]
        assert any("utf8mb3_general_ci" in c for c in collations)

        # 服务端应用路径：改字符集并校验
        results = q.execute(profile,
                            f"ALTER DATABASE `{db}` CHARACTER SET utf8mb4 "
                            "COLLATE utf8mb4_general_ci")
        assert all(r["kind"] == "update" for r in results)
        assert _schema_cs_cl(q, profile, db) == ("utf8mb4", "utf8mb4_general_ci")
    finally:
        q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
        connection_service.close(profile.id)
