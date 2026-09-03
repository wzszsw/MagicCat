"""M22 测试：视图/例程/触发器 对象操作通路（复制 DDL 数据源 + DROP）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_view_routine_trigger_ddl_and_drop(mysql_env, connection_service):
    from magiccat.services.ddl_service import DdlService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M22", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    meta = MetadataService(connection_service)
    ddl = DdlService(connection_service)
    db = f"mc_m22_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE DATABASE `{db}`")
        q.execute(profile, f"CREATE TABLE `{db}`.`t` (id INT PRIMARY KEY, v VARCHAR(20))")
        q.execute(profile, f"CREATE VIEW `{db}`.`v` AS SELECT id FROM `{db}`.`t`")
        q.execute(profile, (
            "DELIMITER $$\n"
            f"CREATE PROCEDURE `{db}`.`p`() BEGIN SELECT 1; END$$\n"
            "DELIMITER ;\n"))
        q.execute(profile, (
            "DELIMITER $$\n"
            f"CREATE TRIGGER `{db}`.`tr` AFTER INSERT ON `{db}`.`t` FOR EACH ROW "
            "BEGIN SET @x = 1; END$$\n"
            "DELIMITER ;\n"))

        assert ddl.show_create_view(profile, db, "v").startswith("CREATE")
        proc_sql = ddl.show_create_routine(profile, db, "p", "PROCEDURE")
        assert "CREATE" in proc_sql and "PROCEDURE" in proc_sql.upper()
        trig_sql = ddl.show_create_trigger(profile, db, "tr")
        assert trig_sql.startswith("CREATE") and "TRIGGER `tr`" in trig_sql

        # 与对象树“删除对象”动作相同的 DDL
        q.execute(profile, f"DROP TRIGGER IF EXISTS `{db}`.`tr`")
        q.execute(profile, f"DROP PROCEDURE IF EXISTS `{db}`.`p`")
        q.execute(profile, f"DROP VIEW IF EXISTS `{db}`.`v`")
        assert meta.triggers(profile, db) == []
        assert meta.routines(profile, db) == []
        assert [t for t in meta.tables(profile, db) if t["type"] == "VIEW"] == []
    finally:
        q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
        connection_service.close(profile.id)
