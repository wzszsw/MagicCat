"""M54 测试：数据页保存改为单连接批量执行（更新落库）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_save_all_batch_updates(qtbot, mysql_env, connection_service):
    from PySide6.QtCore import QModelIndex

    from magiccat.services.data_service import DataService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.data_table import DataTableWidget

    profile = ConnectionProfile(name="M54", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    table = f"mc_m54_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE TABLE `{table}` (id INT PRIMARY KEY, v VARCHAR(20))")
        q.execute(profile, f"INSERT INTO `{table}` VALUES (1, 'a'), (2, 'b')")
        w = DataTableWidget(profile, "test", "test", table, DataService(connection_service),
                            MetadataService(connection_service))
        qtbot.addWidget(w)

        def loaded() -> bool:
            return w._model is not None and w._model.rowCount() == 2

        qtbot.waitUntil(loaded, timeout=25_000)

        # 编辑两行（含空串→NULL 语义），走“保存更改”
        w._model.setData(w._model.index(0, 1, QModelIndex()), "x")
        w._model.setData(w._model.index(1, 1, QModelIndex()), "y")
        w._save_all()

        def saved() -> bool:
            if w._busy:
                return False
            rows = q.execute(profile, f"SELECT id, v FROM `{table}` ORDER BY id")
            vals = rows[0]["rows"]
            return vals == [["1", "x"], ["2", "y"]]

        qtbot.waitUntil(saved, timeout=25_000)
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        connection_service.close(profile.id)
