"""M14 测试：多标签并行执行（不再全局锁）与复制 DDL 通路。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_parallel_execution_qt(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="M14", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    idx = win.profile_combo.findData(profile.id)
    win.profile_combo.setCurrentIndex(idx)

    # 标签1：较长查询；标签2：立刻发起第二条 —— 不应被全局锁拦截
    editor1 = win._active_editor()
    editor1.setPlainText("SELECT 1 AS a1, SLEEP(0.6)")
    win._run_all()
    assert win.act_run.isEnabled(), "执行中不应禁用按钮（支持并行）"

    editor2 = win._new_editor()
    editor2.setPlainText("SELECT 2 AS a2")
    win._run_all()

    def both_done() -> bool:
        # 每查询标签独立结果面板：分别看两个工作区的日志
        logs = [getattr(ws, "result_panel", None) for ws in [editor1, editor2]]
        texts = []
        for lp in logs:
            if lp is not None and hasattr(lp, "_log"):
                texts.append(lp._log.toPlainText())
        joined = "\n".join(texts)
        return "SELECT 1 AS a1" in joined and "SELECT 2 AS a2" in joined and joined.count("[OK]") >= 2

    qtbot.waitUntil(both_done, timeout=30_000)
    connection_service.close(profile.id)


def test_copy_create_sql_via_ddl_service(mysql_env, connection_service):
    from magiccat.services.ddl_service import DdlService
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M14b", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    table = f"mc_m14_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE TABLE `{table}` (id INT PRIMARY KEY, v VARCHAR(20))")
        sql = DdlService(connection_service).show_create(profile, "test", table)
        assert sql.startswith("CREATE TABLE")
        assert "PRIMARY KEY" in sql
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        connection_service.close(profile.id)
