"""M77 测试：database 级与 schema 级「新建查询」正确发出 new_query_requested（含库/模式定位）。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.ui.object_explorer import ObjectExplorer


def _make_explorer(qtbot, connection_service):
    ex = ObjectExplorer(connection_service, None)
    qtbot.addWidget(ex)
    return ex


def _db_node(ex, profile, dbname):
    from magiccat.ui import object_explorer as oe

    pi = ex.topLevelItem(0) if ex.topLevelItemCount() else None
    if pi is None:
        pi = __import__("PySide6.QtWidgets", fromlist=["QTreeWidgetItem"]).QTreeWidgetItem([profile.name])
        pi.setData(0, 0x0100, {oe.KIND_KEY: "profile", oe.DATA_KEY: {"profile_id": profile.id}})
        ex.addTopLevelItem(pi)
    db = oe._make_item(dbname, "database", schema=dbname)
    pi.addChild(db)
    return db, pi


def test_database_level_new_query(qtbot, connection_service):
    profile = ConnectionProfile(name="M77", group=DEFAULT_GROUP, host="127.0.0.1", port=3306)
    connection_service.add(profile)
    ex = _make_explorer(qtbot, connection_service)
    db, _pi = _db_node(ex, profile, "testdb")

    emitted = []
    ex.new_query_requested.connect(lambda *a: emitted.append(a))
    ex._new_query(db)
    assert emitted, "应发出 new_query_requested"
    assert emitted[0] == (profile.id, "testdb", "")


def test_schema_level_new_query(qtbot, connection_service):
    from magiccat.ui import object_explorer as oe

    profile = ConnectionProfile(name="M77b", group=DEFAULT_GROUP, host="127.0.0.1",
                                port=5432, provider_key="postgresql")
    connection_service.add(profile)
    ex = _make_explorer(qtbot, connection_service)
    db, _pi = _db_node(ex, profile, "a")
    schema_node = oe._make_item("public", "schema", schema="public", database="a")
    db.addChild(schema_node)

    emitted = []
    ex.new_query_requested.connect(lambda *a: emitted.append(a))
    ex._new_query(schema_node)
    assert emitted, "应发出 new_query_requested"
    assert emitted[0] == (profile.id, "a", "public")
