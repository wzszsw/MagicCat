"""M29 测试：表设计器索引可视化增删（普通/UNIQUE）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_designer_index_add_remove(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.table_designer import TableDesignerDialog

    profile = ConnectionProfile(name="M29", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    meta = MetadataService(connection_service)
    table = f"mc_m29_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE TABLE `{table}` (id INT PRIMARY KEY, a INT, b INT)")
        dialog = TableDesignerDialog(profile, "test", table, connection_service)
        qtbot.addWidget(dialog)

        def loaded() -> bool:
            return bool(dialog._orig_indexes)

        qtbot.waitUntil(loaded, timeout=25_000)

        def orig_has(name: str) -> bool:
            return any(g["index_name"] == name for g in dialog._orig_indexes)

        def server_names() -> set[str]:
            return {g["index_name"] for g in meta.indexes(profile, "test", table)}

        # 新增普通索引并应用（应用后如真实 UI 一样重载快照）
        dialog.add_index("idx_a", ["a"], unique=False)
        sql = dialog._build_sql(dialog._read_columns())
        assert "ADD INDEX `idx_a` (`a`)" in sql
        assert all(r["kind"] == "update" for r in q.execute(profile, sql))
        assert "idx_a" in server_names()
        dialog._load()
        qtbot.waitUntil(lambda: orig_has("idx_a"), timeout=25_000)

        # 新增 UNIQUE 索引
        dialog.add_index("idx_b", ["b"], unique=True)
        sql2 = dialog._build_sql(dialog._read_columns())
        assert "ADD UNIQUE INDEX `idx_b` (`b`)" in sql2
        assert all(r["kind"] == "update" for r in q.execute(profile, sql2))
        assert "idx_b" in server_names()
        dialog._load()
        qtbot.waitUntil(lambda: orig_has("idx_b"), timeout=25_000)

        # 删除 UNIQUE 索引，保留普通索引
        dialog.remove_index("idx_b")
        sql3 = dialog._build_sql(dialog._read_columns())
        assert "DROP INDEX `idx_b`" in sql3
        assert "ADD INDEX `idx_a`" not in sql3, "未变更的索引不应重建"
        assert all(r["kind"] == "update" for r in q.execute(profile, sql3))
        assert "idx_b" not in server_names()
        assert "idx_a" in server_names()
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        connection_service.close(profile.id)
