"""M19 测试：全库备份恢复（表+视图+例程+触发器 幂等回灌）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_full_schema_backup_restore(tmp_path, mysql_env, connection_service):
    from magiccat.services import backup
    from magiccat.services.data_service import DataService
    from magiccat.services.ddl_service import DdlService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M19", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    data = DataService(connection_service)
    meta = MetadataService(connection_service)
    ddl = DdlService(connection_service)
    db = f"mc_m19_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE DATABASE `{db}`")
        q.execute(profile, (
            f"CREATE TABLE `{db}`.`t_user` (id INT PRIMARY KEY AUTO_INCREMENT, "
            "name VARCHAR(30) NOT NULL, note VARCHAR(50) NULL) ENGINE=InnoDB"))
        q.execute(profile, (
            f"CREATE TABLE `{db}`.`t_audit` (id INT PRIMARY KEY AUTO_INCREMENT, "
            "who VARCHAR(30) NULL) ENGINE=InnoDB"))
        q.execute(profile, f"INSERT INTO `{db}`.`t_user` (name, note) VALUES ('a', NULL), ('b', 'x')")
        q.execute(profile, (
            f"CREATE VIEW `{db}`.`v_users` AS SELECT id, name FROM `{db}`.`t_user`"))
        q.execute(profile, (
            "DELIMITER $$\n"
            f"CREATE PROCEDURE `{db}`.`p_count_users`()\n"
            "BEGIN\n"
            f"  SELECT COUNT(*) AS c FROM `{db}`.`t_user`;\n"
            "END$$\n"
            "DELIMITER ;\n"))
        q.execute(profile, (
            "DELIMITER $$\n"
            f"CREATE TRIGGER `{db}`.`tr_user_ins` AFTER INSERT ON `{db}`.`t_user` "
            "FOR EACH ROW\n"
            "BEGIN\n"
            f"  INSERT INTO `{db}`.`t_audit` (who) VALUES (NEW.name);\n"
            "END$$\n"
            "DELIMITER ;\n"))

        sql_path = tmp_path / "schema.sql"
        res = backup.dump_schema_sql(profile, db, sql_path, data, meta, ddl)
        assert res == {"tables": 2, "rows": 2, "views": 1, "routines": 1,
                       "triggers": 1, "cancelled": False}

        # 整库删除后重建空库 → 恢复（显式目标库，走单连接 setCatalog）
        q.execute(profile, f"DROP DATABASE `{db}`")
        q.execute(profile, f"CREATE DATABASE `{db}`")
        restored = backup.restore_sql_file(profile, sql_path, q, schema=db)
        assert restored["ok"], restored["errors"]

        # 表数据 + 视图 + 过程 + 触发器逐项验证
        rows = q.execute(profile, f"SELECT COUNT(*) FROM `{db}`.`t_user`")
        assert rows[0]["rows"] == [["2"]]
        v = q.execute(profile, f"SELECT COUNT(*) FROM `{db}`.`v_users`")
        assert v[0]["rows"] == [["2"]]
        call = q.execute(profile, f"CALL `{db}`.`p_count_users`()")
        assert call[0]["rows"] == [["2"]]
        q.execute(profile, f"INSERT INTO `{db}`.`t_user` (name) VALUES ('c')")
        audit = q.execute(profile, f"SELECT who FROM `{db}`.`t_audit`")
        assert [r[0] for r in audit[0]["rows"]] == ["c"], "触发器应随插入生效"
        users = q.execute(profile, f"SELECT COUNT(*) FROM `{db}`.`t_user`")
        assert users[0]["rows"] == [["3"]]
    finally:
        q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
        connection_service.close(profile.id)
