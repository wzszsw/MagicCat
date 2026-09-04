"""M3 测试：SQL 文本工具 / 查询执行闭环 / GUI 执行流。"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services.sql_text import (
    format_sql,
    split_sql_statements,
    statement_at_cursor,
)


# ---- 纯文本工具 ----
def test_split_statements_basic():
    sql = "SELECT 1;\n\n-- 注释; 分号在注释里\nSELECT 2;"
    stmts = split_sql_statements(sql)
    # 前导注释归属下一条语句（可原样执行，MySQL 接受前导注释）
    assert stmts[0] == "SELECT 1"
    assert stmts[1].endswith("SELECT 2") and "-- 注释" in stmts[1], stmts


def test_split_statements_respects_strings_and_backticks():
    sql = "INSERT INTO t VALUES ('a;b', `c;d`); UPDATE t SET x = 'it''s; ok'"
    stmts = split_sql_statements(sql)
    assert stmts[0].startswith("INSERT INTO t VALUES ('a;b', `c;d`)")
    assert "it''s; ok" in stmts[1]
    assert len(stmts) == 2


def test_statement_at_cursor():
    text = "SELECT 1;\nSELECT 2;\nSELECT 3"
    assert statement_at_cursor(text, 0) == "SELECT 1"
    assert statement_at_cursor(text, 12) == "SELECT 2"  # 第二条内部
    assert statement_at_cursor(text, len(text)) == "SELECT 3"


def test_format_sql_upper():
    out = format_sql("select id, name from users where id = 1")
    assert out.upper().startswith("SELECT")
    assert "FROM" in out.upper()


# ---- 真实 MySQL 执行闭环 ----
def test_query_service_execute_flow(mysql_env, connection_service):
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M3", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    svc = QueryService(connection_service)
    table = f"mc_m3_{int(time.time() * 1000)}"

    try:
        ddl = (
            f"CREATE TABLE `{table}` (id INT PRIMARY KEY AUTO_INCREMENT, "
            "name VARCHAR(50) NOT NULL, price DECIMAL(10,2) NULL) ENGINE=InnoDB"
        )
        results = svc.execute(profile, ddl)
        assert results[0]["kind"] == "update"
        assert results[0]["affected"] == 0

        # 多条语句混排：插入 × 2 → 查询 → 带分号字符串
        multi = (
            f"INSERT INTO `{table}` (name, price) VALUES ('a', 1.5);"
            f"INSERT INTO `{table}` (name, price) VALUES ('b', NULL);"
            f"SELECT id, name, price FROM `{table}` ORDER BY id;"
        )
        results = svc.execute(profile, multi)
        kinds = [r["kind"] for r in results]
        assert kinds == ["update", "update", "query"]
        assert results[0]["affected"] == 1 and results[1]["affected"] == 1
        rows = results[2]["rows"]
        assert [r[1] for r in rows] == ["a", "b"]
        assert rows[1][2] is None, "NULL 单元格应为 None"

        # 错误语句不中断后续
        broken = "SELECT * FROM no_such_table_xyz; SELECT 42"
        results = svc.execute(profile, broken)
        assert results[0]["kind"] == "error" and results[1]["kind"] == "query"
        assert "no_such_table_xyz" in results[0]["message"]
    finally:
        svc.execute(profile, f"DROP TABLE IF EXISTS `{table}`")


def test_main_window_run_flow(qtbot, mysql_env, connection_service):
    """GUI 闭环：选连接 → 编辑器输入 → 运行 → 结果网格出现数据 → 历史落盘。"""
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.grid import ResultView
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="M3 GUI", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()

    idx = win.profile_combo.findData(profile.id)
    assert idx >= 0
    win.profile_combo.setCurrentIndex(idx)
    win._new_editor()
    editor = win._active_editor()
    editor.setPlainText("SELECT 1 AS one, '你好' AS greeting")
    win._run_current()

    def result_grid_ready() -> bool:
        for i in range(win.result_panel.count()):
            widget = win.result_panel.widget(i)
            if isinstance(widget, ResultView) and widget.model() is not None:
                return widget.model().rowCount() >= 1
        return False

    qtbot.waitUntil(result_grid_ready, timeout=25_000)
    grid = next(win.result_panel.widget(i)
                for i in range(win.result_panel.count())
                if isinstance(win.result_panel.widget(i), ResultView))
    model = grid.model()
    headers = [model.headerData(c, Qt.Horizontal) for c in range(model.columnCount())]
    assert headers == ["one", "greeting"]
    assert model.data(model.index(0, 1)) == "你好"

    # 历史落盘（现为 SQLite）
    from magiccat.services.history import HistoryStore

    recent = HistoryStore(connection_service._store.root).load()
    assert any("SELECT 1 AS one" in s for s in recent)

    connection_service.close(profile.id)
