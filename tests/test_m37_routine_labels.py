"""M37 回归：对象树按 Navicat 显示「函数」与「存储过程」分类。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_tree_routine_labels(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.object_explorer import ObjectExplorer

    profile = ConnectionProfile(name="M37", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    db = f"mc_m37_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE DATABASE `{db}`")
        q.execute(profile, (
            "DELIMITER $$\n"
            f"CREATE PROCEDURE `{db}`.`p_proc`() BEGIN SELECT 1; END$$\n"
            "DELIMITER ;\n"))
        q.execute(profile, (
            f"CREATE FUNCTION `{db}`.`f_func`() RETURNS INT "
            "DETERMINISTIC READS SQL DATA RETURN 1"))

        explorer = ObjectExplorer(connection_service, MetadataService(connection_service))
        qtbot.addWidget(explorer)
        explorer.load_profiles()
        item = explorer.profile_item(profile.id)
        item.setExpanded(True)

        # 先确认服务层确实能列出函数与存储过程
        meta = MetadataService(connection_service)
        routines = meta.routines(profile, db)
        types = [r["type"] for r in routines]
        assert "FUNCTION" in types and "PROCEDURE" in types, f"例程元数据异常: {routines}"

        def db_item():
            for i in range(item.childCount()):
                child = item.child(i)
                info = child.data(0, 0x0100) or {}
                if info.get("kind") == "database" and info.get("data", {}).get("schema") == db:
                    return child
            return None

        # 等库节点出现后展开加载例程
        def wait_db():
            return db_item() is not None

        qtbot.waitUntil(wait_db, timeout=25_000)
        db_item().setExpanded(True)

        def got() -> bool:
            node = db_item()
            if node is None:
                return False
            cats = [node.child(i).text(0) for i in range(node.childCount())]
            # 分类常驻：表/视图/函数/触发器/查询/备份；函数节点含 2 个例程
            func_cat = next((c for i, c in enumerate(cats) if c == "函数"), None)
            joined = "\n".join(cats)
            return (func_cat is not None and node.child(cats.index("函数")).childCount() == 2
                    and "存储过程" not in joined and "例程" not in joined)

        qtbot.waitUntil(got, timeout=25_000)
    finally:
        q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
        connection_service.close(profile.id)
