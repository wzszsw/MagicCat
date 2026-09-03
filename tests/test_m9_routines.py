"""M9 测试：DELIMITER 支持（存储过程多语句开发）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services.sql_text import split_sql_statements, statement_at_cursor


def test_split_with_delimiter_directive():
    text = (
        "SELECT 1;\n"
        "DELIMITER $$\n"
        "CREATE PROCEDURE `p`()\n"
        "BEGIN\n"
        "  SELECT 2;\n"
        "  SET @x = 1;\n"
        "END$$\n"
        "DELIMITER ;\n"
        "CALL `p`();\n"
    )
    stmts = split_sql_statements(text)
    assert len(stmts) == 3, stmts
    assert all("DELIMITER" not in s for s in stmts)
    routine = stmts[1]
    assert routine.startswith("CREATE PROCEDURE")
    # 例程整体作为一条语句：体内分号保留
    assert routine.count(";") == 2 and "BEGIN" in routine and "END" in routine
    assert stmts[2] == "CALL `p`()"

    # 光标落在例程体内 → 返回整条例程
    pos = text.find("SET @x")
    seg = statement_at_cursor(text, pos)
    assert seg is not None and seg.startswith("CREATE PROCEDURE") and seg.count(";") == 2


def test_split_without_delimiter_unchanged():
    text = "SELECT 'a;b'; UPDATE t SET x = 1"
    assert split_sql_statements(text) == ["SELECT 'a;b'", "UPDATE t SET x = 1"]


def test_create_call_drop_procedure(mysql_env, connection_service):
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M9", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    proc = f"mc_m9_p_{int(time.time() * 1000)}"
    try:
        script = (
            f"DELIMITER $$\n"
            f"CREATE PROCEDURE `test`.`{proc}`()\n"
            f"BEGIN\n"
            f"  SELECT 42 AS answer;\n"
            f"END$$\n"
            f"DELIMITER ;\n"
        )
        results = q.execute(profile, script)
        assert len(results) == 1 and results[0]["kind"] == "update", results

        call = q.execute(profile, f"CALL `test`.`{proc}`()")
        assert call[0]["kind"] == "query"
        assert call[0]["rows"] == [["42"]]
    finally:
        q.execute(profile, f"DROP PROCEDURE IF EXISTS `test`.`{proc}`")
        connection_service.close(profile.id)
