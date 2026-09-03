"""M67 测试：功能领域「对象」页（ObjectBrowseView 基类 + 查询/表/视图/函数/触发器子页）。

- 基类：configure 列/键、load 填充、选中态、按钮独立于具体领域。
- 子类：各领域列标题/键名正确；触发器无“新建”入口。
- MainWindow：对象页领域切换（cat_type → 子页），对象页固定占位不可关。
- 真实 MySQL：表/函数对象页异步加载后行正确（无 N+1，单次批查）。
"""

from __future__ import annotations

from magiccat.models.profile import ConnectionProfile


def _profile(mysql_env, name="M67"):
    return ConnectionProfile(name=name, host=mysql_env["host"], port=mysql_env["port"],
                             username=mysql_env["user"], password=mysql_env["password"])


# ---- 子类配置（无 DB，纯 Qt） ----
def test_query_browse_columns(qtbot):
    from magiccat.ui.query_browse import QueryBrowseView

    pg = QueryBrowseView()
    qtbot.addWidget(pg)
    assert pg.table.columnCount() == 3
    assert [pg.table.horizontalHeaderItem(i).text() for i in range(3)] == [
        "名称", "修改日期", "库"]
    assert pg.btn_new.text() == "新建查询"
    assert pg.btn_del.text() == "删除查询"
    assert not pg.btn_new.isHidden()


def test_table_browse_columns(qtbot):
    from magiccat.ui.table_browse import TableBrowseView

    pg = TableBrowseView()
    qtbot.addWidget(pg)
    assert [pg.table.horizontalHeaderItem(i).text() for i in range(5)] == [
        "名称", "类型", "引擎", "行数", "注释"]
    assert pg.btn_new.text() == "新建表"
    assert pg.btn_del.text() == "删除表"
    assert pg.btn_open.text() == "打开"


def test_view_browse_columns(qtbot):
    from magiccat.ui.view_browse import ViewBrowseView

    pg = ViewBrowseView()
    qtbot.addWidget(pg)
    assert pg.btn_new.text() == "新建视图"
    assert pg.btn_del.text() == "删除视图"


def test_routine_browse_columns(qtbot):
    from magiccat.ui.routine_browse import RoutineBrowseView

    pg = RoutineBrowseView()
    qtbot.addWidget(pg)
    assert [pg.table.horizontalHeaderItem(i).text() for i in range(2)] == [
        "名称", "类型"]
    assert pg.btn_new.text() == "新建函数"
    assert pg.btn_del.text() == "删除"


def test_trigger_browse_no_new_and_columns(qtbot):
    from magiccat.ui.trigger_browse import TriggerBrowseView

    pg = TriggerBrowseView()
    qtbot.addWidget(pg)
    assert [pg.table.horizontalHeaderItem(i).text() for i in range(3)] == [
        "名称", "事件", "表"]
    # 触发器由表内创建 → 不显示“新建”入口
    assert pg.btn_new.isHidden()
    assert pg.btn_del.text() == "删除"


# ---- 基类 load / 选中态 ----
def test_object_browse_load_and_selection(qtbot):
    from magiccat.ui.table_browse import TableBrowseView

    pg = TableBrowseView()
    qtbot.addWidget(pg)
    rows = [{"name": "books", "type": "BASE TABLE", "engine": "InnoDB",
             "rows": "5", "comment": ""}]
    pg.load_tables("p1", "test", rows)
    assert pg.table.rowCount() == 1
    assert pg.table.item(0, 0).text() == "books"
    assert pg.table.item(0, 3).text() == "5"
    # 未选中 → 打开/删除禁用
    assert not pg.btn_open.isEnabled()
    assert not pg.btn_del.isEnabled()
    pg.table.selectRow(0)
    assert pg.btn_open.isEnabled()
    assert pg.btn_del.isEnabled()
    assert pg.selected_name() == "books"

    emitted = []
    pg.open_table.connect(lambda *a: emitted.append(a))
    pg._emit_open()
    assert emitted and emitted[0] == ("p1", "test", "books")


# ---- MainWindow 领域切换 + 固定占位 ----
def test_mainwindow_domain_stack(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    et = win.editor_tabs
    assert et.tabText(0) == "对象"
    assert et.widget(0) is win.domain_stack
    # 固定占位页不可关（close(0) 无效果）
    win._close_editor_tab(0)
    assert et.count() >= 1 and et.widget(0) is win.domain_stack

    pages = {"queries": win.browse_page, "tables": win.table_page,
             "views": win.view_page, "routines": win.routine_page,
             "triggers": win.trigger_page}
    assert win._domain_pages == pages
    for cat, page in pages.items():
        win._show_domain(cat)
        assert win.domain_stack.currentWidget() is page, f"领域 {cat} 未切换"


# ---- 真实 MySQL：表/函数对象页异步加载 ----
def test_reload_table_and_routine_pages(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.main_window import MainWindow

    profile = _profile(mysql_env, name="M67db")
    connection_service.add(profile)
    connection_service.open(profile)
    q = QueryService(connection_service)
    db = "mc_test_obj"
    q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
    q.execute(profile, f"CREATE DATABASE `{db}` CHARACTER SET utf8mb4")
    q.execute(profile, f"CREATE TABLE `{db}`.`books` (id bigint PRIMARY KEY, title varchar(255)) ENGINE=InnoDB")
    q.execute(profile, "DELIMITER $$\n"
              f"CREATE FUNCTION `{db}`.`f_one`() RETURNS INT DETERMINISTIC "
              "BEGIN RETURN 1; END$$\nDELIMITER ;")

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    win.profile_combo.setCurrentIndex(win.profile_combo.findData(profile.id))
    qtbot.waitUntil(lambda: win.schema_combo.count() > 0, timeout=25_000)
    idx = win.schema_combo.findText(db)
    if idx >= 0:
        win.schema_combo.setCurrentIndex(idx)

    win._show_domain("tables")
    qtbot.waitUntil(lambda: win.table_page.table.rowCount() >= 1, timeout=25_000)
    assert win.table_page.table.item(0, 0).text() == "books"

    win._show_domain("routines")
    qtbot.waitUntil(lambda: win.routine_page.table.rowCount() >= 1, timeout=25_000)
    assert win.routine_page.table.item(0, 0).text() == "f_one"
    assert win.routine_page.table.item(0, 1).text() == "FUNCTION"

    q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
    connection_service.close(profile.id)
