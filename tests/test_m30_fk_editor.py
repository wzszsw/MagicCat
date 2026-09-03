"""M30 测试：表设计器外键可视化增删。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_designer_fk_add_remove(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.table_designer import TableDesignerDialog

    profile = ConnectionProfile(name="M30", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    meta = MetadataService(connection_service)
    suffix = int(time.time() * 1000)
    parent = f"mc_m30_parent_{suffix}"
    child = f"mc_m30_child_{suffix}"
    try:
        q.execute(profile, f"CREATE TABLE `{parent}` (id INT PRIMARY KEY, v VARCHAR(10))")
        q.execute(profile, f"CREATE TABLE `{child}` (id INT PRIMARY KEY, pid INT NULL)")
        dialog = TableDesignerDialog(profile, "test", child, connection_service)
        qtbot.addWidget(dialog)

        def loaded() -> bool:
            return bool(dialog._orig_indexes) and child in [
                t["name"] for t in meta.tables(profile, "test")]

        qtbot.waitUntil(loaded, timeout=25_000)

        def server_fk_names() -> set[str]:
            return {f["constraint_name"] for f in meta.foreign_keys(profile, "test", child)}

        def orig_has(name: str) -> bool:
            return any(g["constraint_name"] == name for g in dialog._orig_fks)

        # 新增 CASCADE 外键并应用
        dialog.add_fk("fk_pid", "pid", parent, "id", on_delete="CASCADE")
        sql = dialog._build_sql(dialog._read_columns())
        assert ("ADD CONSTRAINT `fk_pid` FOREIGN KEY (`pid`) "
                "REFERENCES `test`.`mc_m30_parent_" in sql or "REFERENCES `test`.`" + parent in sql)
        assert "ON DELETE CASCADE" in sql
        assert all(r["kind"] == "update" for r in q.execute(profile, sql))
        assert "fk_pid" in server_fk_names()
        row = next(f for f in meta.foreign_keys(profile, "test", child)
                   if f["constraint_name"] == "fk_pid")
        assert row["on_delete"] == "CASCADE" and row["ref_table"] == parent
        dialog._load()
        qtbot.waitUntil(lambda: orig_has("fk_pid"), timeout=25_000)

        # 删除外键并应用
        dialog.remove_fk("fk_pid")
        sql2 = dialog._build_sql(dialog._read_columns())
        assert "DROP FOREIGN KEY `fk_pid`" in sql2
        assert all(r["kind"] == "update" for r in q.execute(profile, sql2))
        assert "fk_pid" not in server_fk_names()
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{child}`")
        q.execute(profile, f"DROP TABLE IF EXISTS `{parent}`")
        connection_service.close(profile.id)
