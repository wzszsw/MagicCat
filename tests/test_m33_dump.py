"""M33 测试：数据库转储 SQL（结构和数据 / 仅结构）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_dump_full_vs_structure_only(tmp_path, mysql_env, connection_service):
    from magiccat.services import backup
    from magiccat.services.data_service import DataService
    from magiccat.services.ddl_service import DdlService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M33", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    data = DataService(connection_service)
    meta = MetadataService(connection_service)
    ddl = DdlService(connection_service)
    db = f"mc_m33_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE DATABASE `{db}`")
        q.execute(profile, (
            f"CREATE TABLE `{db}`.`t` (id INT PRIMARY KEY, v VARCHAR(20) NOT NULL)"))
        q.execute(profile, f"INSERT INTO `{db}`.`t` VALUES (1, 'a'), (2, 'b')")

        full_path = tmp_path / "full.sql"
        res = backup.dump_schema_sql(profile, db, full_path, data, meta, ddl, with_data=True)
        assert res["rows"] == 2
        full_text = full_path.read_text(encoding="utf-8")
        assert "CREATE TABLE" in full_text and "INSERT INTO" in full_text

        schema_path = tmp_path / "schema.sql"
        res2 = backup.dump_schema_sql(profile, db, schema_path, data, meta, ddl,
                                      with_data=False)
        assert res2["rows"] == 0
        schema_text = schema_path.read_text(encoding="utf-8")
        assert "CREATE TABLE" in schema_text
        assert "INSERT INTO" not in schema_text, "仅结构不应包含数据 INSERT"
    finally:
        q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
        connection_service.close(profile.id)
