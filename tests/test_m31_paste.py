"""M31 测试：数据页批量粘贴 TSV（Excel 复制）并标记待保存。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_paste_tsv_marks_dirty(qtbot, mysql_env, connection_service):
    from PySide6.QtCore import QModelIndex
    from PySide6.QtGui import QGuiApplication

    from magiccat.services.data_service import DataService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.data_table import DataTableWidget

    profile = ConnectionProfile(name="M31", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    table = f"mc_m31_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE TABLE `{table}` (id INT PRIMARY KEY, a VARCHAR(10), b INT)")
        q.execute(profile, f"INSERT INTO `{table}` VALUES (1, 'old', 0), (2, 'old2', 1)")
        w = DataTableWidget(profile, "test", table, DataService(connection_service),
                            MetadataService(connection_service))
        qtbot.addWidget(w)

        def loaded() -> bool:
            return w._model is not None and w._model.rowCount() >= 1

        qtbot.waitUntil(loaded, timeout=25_000)
        # 把游标放在 (0,1)，从剪贴板粘贴两行两列不等宽
        w.view.setCurrentIndex(w._model.index(0, 1, QModelIndex()))
        QGuiApplication.clipboard().setText("x\t5\ny\t6")
        w._paste_from_clipboard()
        model = w._model
        assert model.edits_of(0) == {1: "x", 2: "5"}
        assert model.edits_of(1) == {1: "y", 2: "6"}
        assert "粘贴" in w.status_label.text()
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        connection_service.close(profile.id)
