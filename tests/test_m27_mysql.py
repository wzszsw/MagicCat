"""M27 测试：EXPLAIN 执行计划 + 数据页默认主键序（MySQL 完备度）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def _profile(mysql_env: dict) -> ConnectionProfile:
    return ConnectionProfile(name="M27", group=DEFAULT_GROUP, database="test",
                             host=mysql_env["host"], port=mysql_env["port"],
                             username=mysql_env["user"], password=mysql_env["password"])


def test_explain_select(mysql_env, connection_service):
    from magiccat.services.query_service import QueryService

    profile = _profile(mysql_env)
    connection_service.add(profile)
    q = QueryService(connection_service)
    table = f"mc_m27_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE TABLE `{table}` (id INT PRIMARY KEY, v INT)")
        q.execute(profile, f"INSERT INTO `{table}` VALUES (1,10),(2,20)")
        res = q.execute(profile, f"EXPLAIN SELECT * FROM `{table}` WHERE v > 5")
        assert res[0]["kind"] == "query"
        cols = res[0]["columns"]
        assert {"id", "select_type", "table"}.issubset(cols)
        assert res[0]["rows"]
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        connection_service.close(profile.id)


def test_data_page_default_pk_order(qtbot, mysql_env, connection_service):
    from magiccat.services.data_service import DataService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.data_table import DataTableWidget

    profile = _profile(mysql_env)
    connection_service.add(profile)
    q = QueryService(connection_service)
    table = f"mc_m27b_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE TABLE `{table}` (id INT PRIMARY KEY, v INT)")
        q.execute(profile, f"INSERT INTO `{table}` VALUES (3,33),(1,11),(2,22)")

        w = DataTableWidget(profile, "test", "test", table,
                            DataService(connection_service),
                            MetadataService(connection_service))
        qtbot.addWidget(w)

        def loaded() -> bool:
            return w._model is not None and w._model.rowCount() == 3

        qtbot.waitUntil(loaded, timeout=25_000)
        ids = [w._model.index(r, 0).data() for r in range(3)]
        assert ids == ["1", "2", "3"], f"未按主键稳定排序: {ids}"
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        connection_service.close(profile.id)
