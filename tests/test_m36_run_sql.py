"""M36 测试：运行 SQL 文件（以库为默认目标，未加前缀语句正确落地）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_run_sql_file_target_schema(tmp_path, mysql_env, connection_service):
    from magiccat.services import backup
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M36", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    meta = MetadataService(connection_service)
    db = f"mc_m36_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE DATABASE `{db}`")
        sql_file = tmp_path / "run.sql"
        sql_file.write_text(
            "CREATE TABLE `t` (id INT PRIMARY KEY, v VARCHAR(10));\n"
            "INSERT INTO `t` VALUES (1, 'a'), (2, 'b');\n",
            encoding="utf-8")
        # 未加库前缀的表名/语句：运行后应落在目标库 schema 下
        res = backup.restore_sql_file(profile, sql_file, q, schema=db)
        assert res["ok"], res["errors"]
        names = {t["name"] for t in meta.tables(profile, db)}
        assert "t" in names
        rows = q.execute(profile, f"SELECT COUNT(*) FROM `{db}`.`t`")
        assert rows[0]["rows"] == [["2"]]
    finally:
        q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
        connection_service.close(profile.id)
