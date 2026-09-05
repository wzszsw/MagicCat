"""M96 回归：查询工作区隔离 JDBC Catalog/Schema 上下文。"""

from __future__ import annotations

import json

from magiccat.models.profile import ConnectionProfile


class _FakeConnections:
    def __init__(self, profile: ConnectionProfile) -> None:
        self.profile = profile
        self.opened: set[str] = set()

    def is_open(self, profile_id: str) -> bool:
        return profile_id in self.opened

    def open(self, profile: ConnectionProfile) -> None:
        self.opened.add(profile.id)


def test_workspace_context_is_per_tab(qtbot):
    from magiccat.ui.editor import SqlEditorWidget
    from magiccat.ui.query_workspace import QueryWorkspace

    first = QueryWorkspace(SqlEditorWidget())
    second = QueryWorkspace(SqlEditorWidget())
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    first.database_combo.addItems(["db_a", "db_b"])
    second.database_combo.addItems(["db_a", "db_b"])
    first.schema_combo.addItems(["public", "app"])
    second.schema_combo.addItems(["public", "audit"])
    first.schema_combo.setEnabled(True)
    second.schema_combo.setEnabled(True)

    first.set_database("db_b")
    first.set_schema("app")

    assert first.selected_catalog() == "db_b"
    assert first.selected_schema() == "app"
    assert second.selected_catalog() == "db_a"
    assert second.selected_schema() == "public"


def test_query_service_context_arguments_and_mysql_null_schema(monkeypatch):
    from magiccat.services import query_service as module

    profile = ConnectionProfile(name="mysql", provider_key="MYSQL")
    connections = _FakeConnections(profile)
    calls: list[tuple] = []

    class _Executor:
        @staticmethod
        def executeCancelable(*args):
            calls.append(args)
            return json.dumps({"kind": "update", "affected": 0})

    class _Runtime:
        @staticmethod
        def jclass(_name):
            return _Executor

    monkeypatch.setattr(module, "get_runtime", lambda: _Runtime())
    result = module.QueryService(connections).execute(
        profile, "SELECT 1", database="db_a", schema="should-be-null")

    assert result[0]["kind"] == "update"
    assert len(calls) == 1
    assert calls[0][:5] == (profile.id, "db_a", None, "SELECT 1", 2000)
    assert isinstance(calls[0][5], str) and calls[0][5]


def test_query_service_preserves_legacy_executor_without_context(monkeypatch):
    from magiccat.services import query_service as module

    profile = ConnectionProfile(name="mysql", provider_key="MYSQL")
    connections = _FakeConnections(profile)
    calls: list[tuple] = []

    class _Executor:
        @staticmethod
        def executeCancelable(*args):
            calls.append(args)
            return json.dumps({"kind": "update", "affected": 0})

    class _Runtime:
        @staticmethod
        def jclass(_name):
            return _Executor

    monkeypatch.setattr(module, "get_runtime", lambda: _Runtime())
    module.QueryService(connections).execute(profile, "SELECT 1")

    assert len(calls) == 1
    assert calls[0][0] == profile.id
    assert len(calls[0]) == 4


def test_workspace_context_uses_catalog_and_schema_for_pg(qtbot):
    from magiccat.ui.editor import SqlEditorWidget
    from magiccat.ui.main_window import MainWindow
    from magiccat.ui.query_workspace import QueryWorkspace

    profile = ConnectionProfile(name="pg", provider_key="PGSQL")
    workspace = QueryWorkspace(SqlEditorWidget())
    qtbot.addWidget(workspace)
    workspace.database_combo.addItem("app_db")
    workspace.schema_combo.addItem("app")
    workspace.schema_combo.setEnabled(True)
    workspace.set_database("app_db")
    workspace.set_schema("app")

    assert MainWindow._workspace_context(workspace, profile) == ("app_db", "app")

    workspace.set_schema("")
    workspace.schema_combo.setCurrentIndex(-1)
    assert MainWindow._workspace_context(workspace, profile) == ("app_db", None)

    workspace.schema_combo.setEnabled(False)
    assert MainWindow._workspace_context(workspace, profile) == ("app_db", None)


def test_workspace_hides_schema_for_mysql(qtbot):
    from magiccat.ui.editor import SqlEditorWidget
    from magiccat.ui.query_workspace import QueryWorkspace

    workspace = QueryWorkspace(SqlEditorWidget())
    qtbot.addWidget(workspace)
    workspace.set_schema_visible(False)

    assert workspace.schema_combo.isHidden()

    workspace.set_schema_visible(True)
    assert not workspace.schema_combo.isHidden()


def test_workspace_context_combos_use_icons_without_text_labels(qtbot):
    from magiccat.ui.editor import SqlEditorWidget
    from magiccat.ui.icons import icon
    from magiccat.ui.query_workspace import QueryWorkspace

    workspace = QueryWorkspace(SqlEditorWidget())
    qtbot.addWidget(workspace)
    workspace.database_combo.addItem(icon("database"), "app_db")
    workspace.schema_combo.addItem(icon("schema"), "public")

    assert not workspace.database_combo.itemIcon(0).isNull()
    assert not workspace.schema_combo.itemIcon(0).isNull()
    assert all(label.text() not in {"连接:", "库:", "模式:"}
               for label in workspace.findChildren(type(workspace.status_label)))


def test_new_query_from_database_or_schema_keeps_requested_location(
    qtbot, connection_service, monkeypatch
):
    from magiccat.ui import main_window as main_window_module
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(
        name="pg-context", provider_key="PGSQL", database="postgres"
    )
    connection_service.add(profile)

    class _Metadata:
        @staticmethod
        def databases(_profile):
            return [{"name": "postgres"}, {"name": "app_db"}]

        @staticmethod
        def schemas(_profile, _database):
            return [{"name": "public"}, {"name": "app"}]

        @staticmethod
        def schema_tables_in_database(_profile, _database, _schema):
            return []

        @staticmethod
        def schema_columns_in_database(_profile, _database, _schema):
            return []

    def immediate(work, done, error):
        done(work())

    monkeypatch.setattr(main_window_module, "run_async", immediate)
    win = MainWindow(connection_service, _Metadata())
    qtbot.addWidget(win)

    # 数据库级：Catalog 定位成功，Schema 明确保持空选。
    win._on_new_query_from_explorer(profile.id, "app_db", "")
    database_ws = win._current_query_ws()
    assert database_ws.selected_catalog() == "app_db"
    assert database_ws.selected_schema() is None
    assert database_ws.schema_combo.currentIndex() == -1

    # 模式级：同样的异步流程最终定位到具体 Schema。
    win._on_new_query_from_explorer(profile.id, "app_db", "app")
    schema_ws = win._current_query_ws()
    assert schema_ws.selected_catalog() == "app_db"
    assert schema_ws.selected_schema() == "app"


def test_plain_new_query_inherits_tree_context_only_at_creation(
    qtbot, connection_service, monkeypatch
):
    from magiccat.ui import main_window as main_window_module
    from magiccat.ui.main_window import MainWindow
    from magiccat.ui.object_explorer import _make_item

    profile = ConnectionProfile(
        name="tree-context", provider_key="PGSQL", database="postgres"
    )
    connection_service.add(profile)

    class _Metadata:
        @staticmethod
        def databases(_profile):
            return [{"name": "postgres"}, {"name": "app_db"}]

        @staticmethod
        def schemas(_profile, _database):
            return [{"name": "public"}, {"name": "app"}]

        @staticmethod
        def schema_tables_in_database(_profile, _database, _schema):
            return []

        @staticmethod
        def schema_columns_in_database(_profile, _database, _schema):
            return []

    def immediate(work, done, error):
        done(work())

    monkeypatch.setattr(main_window_module, "run_async", immediate)
    win = MainWindow(connection_service, _Metadata())
    qtbot.addWidget(win)
    profile_item = win.explorer.profile_item(profile.id)
    database_item = _make_item("app_db", "database", schema="app_db")
    schema_item = _make_item("app", "schema", database="app_db", schema="app")
    profile_item.addChild(database_item)
    database_item.addChild(schema_item)

    win.explorer.setCurrentItem(schema_item)
    win._new_editor()
    workspace = win._current_query_ws()
    assert workspace.selected_catalog() == "app_db"
    assert workspace.selected_schema() == "app"

    # 树切到另一个库后，已创建标签仍保留原上下文。
    other = _make_item("postgres", "database", schema="postgres")
    profile_item.addChild(other)
    win.explorer.setCurrentItem(other)
    assert workspace.selected_catalog() == "app_db"
    assert workspace.selected_schema() == "app"


def test_tree_profile_activation_does_not_rewrite_active_query_tab(qtbot):
    from PySide6.QtWidgets import QComboBox, QMainWindow, QTabWidget

    from magiccat.ui.editor import SqlEditorWidget
    from magiccat.ui.main_window import MainWindow
    from magiccat.ui.query_workspace import QueryWorkspace

    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    window.profile_combo = QComboBox()
    window.profile_combo.addItem("连接 A", "p_a")
    window.profile_combo.addItem("连接 B", "p_b")
    window.editor_tabs = QTabWidget()
    workspace = QueryWorkspace(SqlEditorWidget())
    workspace.profile_combo.addItem("连接 A", "p_a")
    workspace.profile_combo.addItem("连接 B", "p_b")
    workspace.profile_combo.setCurrentIndex(0)
    window.editor_tabs.addTab(workspace, "查询")

    window.profile_combo.setCurrentIndex(0)
    MainWindow._set_current_profile(window, "p_b")

    assert window.profile_combo.currentData() == "p_b"
    assert workspace.profile_combo.currentData() == "p_a"
