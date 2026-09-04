"""M4 测试：表数据服务（分页/主键定位增删改）+ 数据页编辑模型。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def _profile(mysql_env: dict) -> ConnectionProfile:
    return ConnectionProfile(name="M4", group=DEFAULT_GROUP, database="test",
                             host=mysql_env["host"], port=mysql_env["port"],
                             username=mysql_env["user"], password=mysql_env["password"])


def _make_table(connection_service, profile, suffix: str, with_pk: bool = True) -> str:
    from magiccat.services.query_service import QueryService

    table = f"mc_m4_{suffix}_{int(time.time() * 1000)}"
    pk = "id INT PRIMARY KEY AUTO_INCREMENT, " if with_pk else ""
    ddl = (f"CREATE TABLE `{table}` ({pk}"
           "name VARCHAR(50) NOT NULL, note VARCHAR(100) NULL, price DECIMAL(10,2) NULL)"
           " ENGINE=InnoDB")
    QueryService(connection_service).execute(profile, ddl)
    return table


def test_data_service_crud(mysql_env, connection_service):
    from magiccat.services.data_service import DataService
    from magiccat.services.query_service import QueryService

    profile = _profile(mysql_env)
    connection_service.add(profile)
    svc = DataService(connection_service)
    q = QueryService(connection_service)
    table = _make_table(connection_service, profile, "crud")
    try:
        q.execute(profile,
                  f"INSERT INTO `{table}` (name, price) VALUES ('a', 1.1),('b', 2.2),('c', NULL)")
        # 分页读取 + 主键 + 总数
        page = svc.load_page(profile, "test", table, offset=0, limit=2)
        assert page["total"] == 3
        assert page["pk"] == ["id"]
        assert len(page["rows"]) == 2
        assert page["truncated"] is True
        second = svc.load_page(profile, "test", table, offset=2, limit=2)
        assert len(second["rows"]) == 1 and second["rows"][0][1] == "c"
        assert second["rows"][0][3] is None  # price NULL

        # 主键定位 UPDATE
        first_id = page["rows"][0][0]
        affected = svc.update_row(profile, "test", table, ["id"], [first_id],
                                  ["name", "price"], ["改名", 9.99])
        assert affected == 1
        rows = q.execute(profile, f"SELECT name, price FROM `{table}` WHERE id = {first_id}")
        assert rows[0]["rows"] == [["改名", "9.99"]]

        # INSERT + DELETE
        assert svc.insert_row(profile, "test", table, ["name", "price"], ["新行", "5.5"]) == 1
        page = svc.load_page(profile, "test", table, offset=0, limit=10)
        new_id = max(int(r[0]) for r in page["rows"])
        assert svc.delete_row(profile, "test", table, ["id"], [new_id]) == 1
        assert svc.load_page(profile, "test", table, offset=0, limit=10)["total"] == 3

        # WHERE / ORDER BY 生效
        filtered = svc.load_page(profile, "test", table, offset=0, limit=10,
                                 where="price IS NOT NULL", order_by="`price` DESC")
        price_col = filtered["columns"].index("price")
        assert [r[price_col] for r in filtered["rows"]] == ["9.99", "2.20"]
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        connection_service.close(profile.id)


def test_update_without_pk_rejected(mysql_env, connection_service):
    from magiccat.services.data_service import DataService
    from magiccat.services.query_service import QueryService

    profile = _profile(mysql_env)
    connection_service.add(profile)
    svc = DataService(connection_service)
    table = _make_table(connection_service, profile, "nopk", with_pk=False)
    try:
        q = QueryService(connection_service)
        q.execute(profile, f"INSERT INTO `{table}` (name) VALUES ('x')")
        import pytest

        with pytest.raises(Exception):  # noqa: B017 —— JPype 上抛 Java 异常
            svc.update_row(profile, "test", table, [], [], ["name"], ["y"])
        assert svc.primary_key(profile, "test", table) == []
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        connection_service.close(profile.id)


def test_data_table_widget_editing(qtbot, mysql_env, connection_service):
    """数据页：加载后可编辑（有主键），改动记录 dirty；无主键表只读。"""
    from PySide6.QtCore import Qt

    from magiccat.services.data_service import DataService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.data_table import DataTableWidget

    profile = _profile(mysql_env)
    connection_service.add(profile)
    q = QueryService(connection_service)
    table = _make_table(connection_service, profile, "gui", with_pk=True)
    nopk = _make_table(connection_service, profile, "guinopk", with_pk=False)
    try:
        q.execute(profile, f"INSERT INTO `{table}` (name, price) VALUES ('a',1.0),('b',2.0)")
        q.execute(profile, f"INSERT INTO `{nopk}` (name) VALUES ('x')")

        data = DataService(connection_service)
        meta = MetadataService(connection_service)
        w = DataTableWidget(profile, "test", "test", table, data, meta)
        qtbot.addWidget(w)

        def loaded() -> bool:
            return w._model is not None and w._model.rowCount() == 2

        qtbot.waitUntil(loaded, timeout=25_000)
        model = w._model
        assert not model.readonly
        assert model.flags(model.index(0, 1)) & Qt.ItemIsEditable

        # 编辑 name 列
        assert model.setData(model.index(0, 1), "改名a")
        assert model.data(model.index(0, 1)) == "改名a"
        assert model.edits_of(0) == {1: "改名a"}

        # 新增行 + 撤销
        model.append_new_row()
        assert model.rowCount() == 3
        model.remove_new_row(2)
        assert model.rowCount() == 2

        # 无主键表 → 只读
        w2 = DataTableWidget(profile, "test", "test", nopk, data, meta)
        qtbot.addWidget(w2)

        def loaded2() -> bool:
            return w2._model is not None and w2._model.rowCount() >= 1

        qtbot.waitUntil(loaded2, timeout=25_000)
        assert w2._model.readonly is True
        assert not (w2._model.flags(w2._model.index(0, 1)) & Qt.ItemIsEditable)
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        q.execute(profile, f"DROP TABLE IF EXISTS `{nopk}`")
        connection_service.close(profile.id)
