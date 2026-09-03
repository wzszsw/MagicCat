"""M52 探针：对象树确为“点击展开才查该层”——展开库不查对象、展开某分类只查一次。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


class _SpyMeta:
    """包装真实 MetadataService，统计各类查询次数。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.databases_calls = 0
        self.tables_calls = 0
        self.routines_calls = 0
        self.triggers_calls = 0
        self.columns_calls = 0

    def databases(self, profile):
        self.databases_calls += 1
        return self._inner.databases(profile)

    def tables(self, profile, schema):
        self.tables_calls += 1
        return self._inner.tables(profile, schema)

    def routines(self, profile, schema):
        self.routines_calls += 1
        return self._inner.routines(profile, schema)

    def triggers(self, profile, schema):
        self.triggers_calls += 1
        return self._inner.triggers(profile, schema)

    def columns(self, profile, schema, table):
        self.columns_calls += 1
        return self._inner.columns(profile, schema, table)


def _category_item(db_item, label: str):
    for i in range(db_item.childCount()):
        if db_item.child(i).text(0) == label:
            return db_item.child(i)
    return None


def test_tree_lazy_on_expand(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.object_explorer import ObjectExplorer

    profile = ConnectionProfile(name="M52", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    db = f"mc_m52_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE DATABASE `{db}`")
        q.execute(profile, f"CREATE TABLE `{db}`.`t1` (id INT PRIMARY KEY)")
        q.execute(profile, (
            "DELIMITER $$\n"
            f"CREATE PROCEDURE `{db}`.`p1`() BEGIN SELECT 1; END$$\n"
            "DELIMITER ;\n"))

        spy = _SpyMeta(MetadataService(connection_service))
        explorer = ObjectExplorer(connection_service, spy)
        qtbot.addWidget(explorer)
        explorer.load_profiles()
        profile_item = explorer.profile_item(profile.id)
        profile_item.setExpanded(True)  # ① 展开连接 → 查库列表

        def db_found() -> bool:
            for i in range(profile_item.childCount()):
                c = profile_item.child(i)
                info = c.data(0, 0x0100) or {}
                if info.get("kind") == "database" and info.get("data", {}).get("schema") == db:
                    return True
            return False

        qtbot.waitUntil(db_found, timeout=25_000)
        assert spy.databases_calls == 1
        assert spy.tables_calls == 0, "展开库前不应查表"

        # ② 展开库 → 只建分类骨架，不应查 表/函数/触发器
        db_item = None
        for i in range(profile_item.childCount()):
            c = profile_item.child(i)
            info = c.data(0, 0x0100) or {}
            if info.get("kind") == "database" and info.get("data", {}).get("schema") == db:
                db_item = c
                break
        db_item.setExpanded(True)

        def skeleton() -> bool:
            return db_item.childCount() >= 5  # 表/视图/函数/触发器/查询/备份

        qtbot.waitUntil(skeleton, timeout=25_000)
        assert spy.tables_calls == 0, "展开库不应查对象（只出骨架）"
        assert spy.routines_calls == 0 and spy.triggers_calls == 0

        def has_real_leaf(item) -> bool:
            for i in range(item.childCount()):
                info = item.child(i).data(0, 0x0100) or {}
                if info.get("kind") not in ("placeholder",):
                    return True
            return False

        # ③ 展开「表」分类 → 才查一次表；函数/触发器仍未查
        cat = _category_item(db_item, "表")
        cat.setExpanded(True)

        def table_loaded() -> bool:
            return has_real_leaf(cat)

        qtbot.waitUntil(table_loaded, timeout=25_000)
        assert spy.tables_calls == 1, "展开「表」应只查一次表"
        assert spy.routines_calls == 0 and spy.triggers_calls == 0

        # ④ 展开「函数」分类 → 查一次函数
        fcat = _category_item(db_item, "函数")
        fcat.setExpanded(True)

        def routine_loaded() -> bool:
            return has_real_leaf(fcat)

        qtbot.waitUntil(routine_loaded, timeout=25_000)
        assert spy.routines_calls == 1 and spy.triggers_calls == 0
    finally:
        q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
        connection_service.close(profile.id)
