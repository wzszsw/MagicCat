"""主窗口（M3）：连接选择 + 多标签 SQL 编辑器 + 执行流 + 结果面板。

执行模型：所有 JDBC 在后台线程执行（run_async），主线程只负责状态切换与结果展示。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from magiccat.models.profile import ConnectionProfile
from magiccat.resources import app_icon_png
from magiccat.services.connection_service import ConnectionService
from magiccat.services.history import HistoryStore
from magiccat.services.metadata_service import MetadataService
from magiccat.services.query_service import QueryService
from magiccat.services.settings import AppSettings
from magiccat.services.sql_text import format_sql
from magiccat.ui.dialogs import ConnectionEditDialog, EnvironmentDialog
from magiccat.ui.job import run_async
from magiccat.ui.monaco_editor import MonacoEditorWidget
from magiccat.ui.object_explorer import ObjectExplorer
from magiccat.ui.theme import apply_theme

logger = logging.getLogger(__name__)

_SYSTEM_SCHEMAS = {"information_schema", "performance_schema", "mysql", "sys"}


def _is_editor(widget) -> bool:
    """判断是否为查询工作区（内部持有编辑器）。"""
    from magiccat.ui.query_workspace import QueryWorkspace

    return isinstance(widget, QueryWorkspace)


class MainWindow(QMainWindow):
    def __init__(self, connections: ConnectionService,
                 metadata: MetadataService | None = None) -> None:
        super().__init__()
        self._connections = connections
        self._metadata = metadata or MetadataService(connections)
        self._query = QueryService(connections)
        self._history = HistoryStore.default()
        self._settings = AppSettings.default()
        self._tab_seq = 0
        self._running = 0
        # 固定“对象”页最近一次从左树获得的连接/Catalog/Schema 上下文。
        self._object_context: tuple[str, str, str] | None = None

        self.setWindowTitle("MagicCat")
        self.setWindowIcon(QIcon(app_icon_png()))
        geometry = self._settings.get("geometry")
        if isinstance(geometry, str) and geometry:
            from PySide6.QtCore import QByteArray

            if self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii"))):
                self.resize(1280, 820)
        else:
            self.resize(1280, 820)
        self._build_central()
        self._build_explorer_dock()
        self._build_info_dock()
        self._build_quick_toolbar()
        self._build_actions()

        self._reload_connection_combo()
        self.statusBar().showMessage("就绪")
        apply_theme(self, self._settings.get("theme", "light"))

        # 计划任务调度（应用运行期间每 60s 检查一次）
        from magiccat.services.tasks import TaskLock, TaskStore

        self._task_store = TaskStore.default()
        self._task_lock = TaskLock()
        self._task_timer = QTimer(self)
        self._task_timer.timeout.connect(self._scan_due_tasks)
        self._task_timer.start(60_000)

    def closeEvent(self, event) -> None:
        try:
            data = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self._settings.set("geometry", data)
        except Exception as exc:  # noqa: BLE001 —— 保存失败不影响退出
            logger.warning("保存窗口几何失败: %s", exc)
        super().closeEvent(event)

    # ---- 布局 ----
    def _build_central(self) -> None:
        # 对象浏览上下文由左侧树跟手；保留隐藏 combo 作为兼容的内部状态，
        # 不把全局连接/库选择器渲染到中央区域。
        self.profile_combo = QComboBox(self)
        self.profile_combo.hide()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        self.schema_combo = QComboBox(self)
        self.schema_combo.hide()
        self.schema_combo.currentIndexChanged.connect(self._reload_query_browse)
        self._edit_actions = ()  # 查询动作条已移至各查询工作区

        # 中央工作区标签页：第 1 页固定「对象」（各功能领域的列表/浏览态占位）
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setTabsClosable(True)
        self.editor_tabs.tabCloseRequested.connect(self._close_editor_tab)
        self.editor_tabs.currentChanged.connect(self._on_query_tab_changed)

        # 「对象」页 = 领域浏览栈：查询、表、视图、函数、触发器五个领域子页
        self.domain_stack = QStackedWidget()
        self._build_query_browse()
        self._build_table_browse()
        self._build_view_browse()
        self._build_routine_browse()
        self._build_trigger_browse()
        self._build_sequence_browse()
        self.domain_stack.addWidget(self.browse_page)
        self.domain_stack.addWidget(self.table_page)
        self.domain_stack.addWidget(self.view_page)
        self.domain_stack.addWidget(self.routine_page)
        self.domain_stack.addWidget(self.trigger_page)
        self.domain_stack.addWidget(self.sequence_page)
        self._domain_pages: dict[str, QWidget] = {
            "queries": self.browse_page, "tables": self.table_page,
            "views": self.view_page, "routines": self.routine_page,
            "triggers": self.trigger_page, "sequences": self.sequence_page}
        self._current_domain = "tables"
        # Navicat 首屏的“对象”工作区默认属于表功能域；查询标签只在用户
        # 点击新建/打开查询后出现，不能让查询域抢占首屏。
        self.domain_stack.setCurrentWidget(self.table_page)
        self.editor_tabs.addTab(self.domain_stack, "对象")
        # 「对象」为固定占位页，不显示关闭按钮
        from PySide6.QtWidgets import QTabBar

        self.editor_tabs.tabBar().setTabButton(0, QTabBar.RightSide, None)

        work = QWidget()
        work_lay = QVBoxLayout(work)
        work_lay.setContentsMargins(0, 0, 0, 0)
        work_lay.setSpacing(0)
        work_lay.addWidget(self.editor_tabs, 1)
        # 查询工具栏包含多个操作控件，默认 sizeHint 会把中央区最小宽度
        # 推到一千像素以上，进而锁死左右 dock 的分隔条。允许中央区水平
        # 压缩，三块区域才能像 Navicat 一样在非最大化窗口中自由调宽。
        self.editor_tabs.setMinimumWidth(0)
        self.editor_tabs.setSizePolicy(QSizePolicy.Policy.Ignored,
                                       QSizePolicy.Policy.Expanding)
        work.setMinimumWidth(0)
        work.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Expanding)
        self.setCentralWidget(work)

    def _build_query_browse(self) -> None:
        """查询领域「对象」子页：新建/删除查询 + 已存查询表格（不做“设计查询”）。"""
        from magiccat.ui.query_browse import QueryBrowseView

        self.browse_page = QueryBrowseView()
        self.browse_page.new_query.connect(self._new_editor)
        self.browse_page.open_query.connect(self._open_saved_query)
        self.browse_page.delete_query.connect(self._delete_saved_query)
        self.browse_page.refresh_requested.connect(self._reload_query_browse)
        self.browse_page.selection_object.connect(self._show_object_info)

    def _build_table_browse(self) -> None:
        """表领域「对象」子页：打开/设计/新建/删除表 + 当前库表列表。"""
        from magiccat.ui.table_browse import TableBrowseView

        self.table_page = TableBrowseView()
        self.table_page.open_table.connect(self._on_open_table)
        self.table_page.design_table.connect(self._on_design_table)
        self.table_page.new_table.connect(lambda: self._quick_create_object("table"))
        self.table_page.delete_table.connect(self._delete_table)
        self.table_page.refresh_requested.connect(self._reload_table_browse)
        self.table_page.selection_object.connect(self._show_object_info)

    def _build_view_browse(self) -> None:
        """视图领域「对象」子页：打开/新建/删除视图 + 当前库视图列表。"""
        from magiccat.ui.view_browse import ViewBrowseView

        self.view_page = ViewBrowseView()
        self.view_page.open_view.connect(self._open_view)
        self.view_page.new_view.connect(lambda: self._quick_create_object("view"))
        self.view_page.delete_view.connect(self._delete_view)
        self.view_page.refresh_requested.connect(self._reload_view_browse)
        self.view_page.selection_object.connect(self._show_object_info)

    def _build_routine_browse(self) -> None:
        """函数领域「对象」子页：打开/新建/删除函数 + 当前库函数/过程列表。"""
        from magiccat.ui.routine_browse import RoutineBrowseView

        self.routine_page = RoutineBrowseView()
        self.routine_page.open_routine.connect(self._open_routine)
        self.routine_page.new_routine.connect(lambda: self._on_create_routine_entry())
        self.routine_page.delete_routine.connect(self._delete_routine)
        self.routine_page.refresh_requested.connect(self._reload_routine_browse)
        self.routine_page.selection_object.connect(self._show_object_info)

    def _build_trigger_browse(self) -> None:
        """触发器领域「对象」子页：打开/删除触发器 + 当前库触发器列表（无新建入口）。"""
        from magiccat.ui.trigger_browse import TriggerBrowseView

        self.trigger_page = TriggerBrowseView()
        self.trigger_page.open_trigger.connect(self._open_trigger)
        self.trigger_page.delete_trigger.connect(self._delete_trigger)
        self.trigger_page.refresh_requested.connect(self._reload_trigger_browse)
        self.trigger_page.selection_object.connect(self._show_object_info)

    def _build_sequence_browse(self) -> None:
        """序列领域「对象」子页：设计/新建/删除序列 + 当前库序列列表（PostgreSQL）。"""
        from magiccat.ui.sequence_browse import SequenceBrowseView

        self.sequence_page = SequenceBrowseView()
        self.sequence_page.design_sequence.connect(self._design_sequence)
        self.sequence_page.new_sequence.connect(self._new_sequence)
        self.sequence_page.delete_sequence.connect(self._delete_sequence)
        self.sequence_page.refresh_requested.connect(self._reload_sequence_browse)
        self.sequence_page.selection_object.connect(self._show_object_info)

    def _on_create_routine_entry(self, profile_id: str | None = None,
                                 schema: str | None = None) -> None:
        """新建函数（对象页动作）：需要连接/库上下文，复用打开向导。"""
        profile = self._current_profile()
        if profile is None:
            QMessageBox.information(self, "新建函数", "请先在工具栏选择连接。")
            return
        schema = schema or (self.schema_combo.currentText() or profile.database)
        if not schema:
            QMessageBox.information(self, "新建函数", "请先选择库。")
            return
        self._on_create_routine(profile.id, schema)

    # ---- 中央工作区状态 ----
    def _on_query_tab_changed(self, index: int) -> None:
        """当前标签切换：对象页激活时刷新列表；查询标签保留自己的上下文。"""
        widget = self.editor_tabs.widget(index)
        is_object_page = widget is self.domain_stack
        if is_object_page:
            self._reload_current_domain()

    def _show_query_domain(self) -> None:
        """顶部「查询」领域图标：切到「对象」页并选中查询浏览子页。"""
        self._set_domain_action("queries")
        self.domain_stack.setCurrentWidget(self.browse_page)
        self.editor_tabs.setCurrentIndex(0)
        self._reload_query_browse()

    def _show_domain(self, cat_type: str, schema: str = "", database: str = "",
                     activate: bool = True) -> None:
        """对象树选中某分类 → 对象页切到对应领域子页并展示列表。"""
        page = self._domain_pages.get(cat_type)
        if page is None:
            return
        self._set_domain_action(cat_type)
        self.domain_stack.setCurrentWidget(page)
        if activate:
            self.editor_tabs.setCurrentIndex(0)
        self._reload_current_domain(schema=schema, database=database)

    def _reload_current_domain(self, schema: str = "", database: str = "") -> None:
        page = self.domain_stack.currentWidget()
        if page is self.browse_page:
            self._reload_query_browse(schema=schema, database=database)
        elif page is self.table_page:
            self._reload_table_browse(schema=schema, database=database)
        elif page is self.view_page:
            self._reload_view_browse(schema=schema, database=database)
        elif page is self.routine_page:
            self._reload_routine_browse(schema=schema, database=database)
        elif page is self.trigger_page:
            self._reload_trigger_browse(schema=schema, database=database)
        elif page is self.sequence_page:
            self._reload_sequence_browse(database=database, schema=schema)
        else:
            page.clear() if hasattr(page, "clear") else None

    def _reload_query_browse(self, profile=None, schema: str = "",
                             database: str = "") -> None:
        """按当前连接/库刷新「查询」对象页列表。"""
        profile = profile or self._current_profile()
        if profile is None:
            self.browse_page.clear()
            self.browse_page.ctx_label.setText("")
            return
        if profile.is_postgres:
            schema = schema or "public"
            database = database or profile.database or ""
        else:
            schema = schema or self.schema_combo.currentText() or profile.database or ""
        self.browse_page.load_queries(profile.id, schema)
        self.browse_page.ctx_label.setText(
            f"{profile.display_name} · {database} · {schema or '默认'}"
            if profile.is_postgres else
            f"{profile.display_name} · {schema or '默认'}")

    def _reload_table_browse(self, profile=None, schema: str = "",
                             database: str = "") -> None:
        """按当前连接/库刷新「表」对象页列表（全库一次批查，无 N+1）。"""
        profile = profile or self._current_profile()
        if profile is None:
            self.table_page.clear()
            self.table_page.ctx_label.setText("")
            return
        if profile.is_postgres:
            schema = schema or "public"
        else:
            schema = schema or self.schema_combo.currentText() or profile.database or ""
        database = database or ""
        if profile.is_postgres and not database:
            # PG/GaussDB 的对象页需要同时知道 Catalog 和 Schema；优先取当前
            # 树节点所属数据库，避免把非初始库误查成 profile.database。
            item = self.explorer.currentItem() if hasattr(self, "explorer") else None
            if item is not None:
                database = self.explorer._database_of(item)
            database = database or profile.database or ""
        self.table_page.ctx_label.setText(
            f"{profile.display_name} · {database} · {schema or '默认'}"
             if profile.is_postgres else
             f"{profile.display_name} · {schema or '默认'}")

        def fetch():
            return self._metadata.schema_tables(profile, schema, database)

        def done(rows: list[dict]) -> None:
            self.table_page.load_tables(profile.id, schema, rows)

        def error(err: str) -> None:
            # 错误不占用表页操作栏，保留当前上下文并用统一错误框提示。
            self.table_page.ctx_label.setText(
                f"{profile.display_name} · {database} · {schema or '默认'}"
                 if profile.is_postgres else
                 f"{profile.display_name} · {schema or '默认'}")
            from magiccat.utils.errors import clean_java_error

            QMessageBox.critical(self, "读取表失败", clean_java_error(err))

        run_async(fetch, done, error)

    def _reload_view_browse(self, profile=None, schema: str = "",
                            database: str = "") -> None:
        """按当前连接/库刷新「视图」对象页列表（复用全库表批查，只取 VIEW）。"""
        profile = profile or self._current_profile()
        if profile is None:
            self.view_page.clear()
            self.view_page.ctx_label.setText("")
            return
        if profile.is_postgres:
            schema = schema or "public"
            if not database:
                item = self.explorer.currentItem() if hasattr(self, "explorer") else None
                if item is not None:
                    database = self.explorer._database_of(item)
                database = database or profile.database or ""
        else:
            schema = schema or self.schema_combo.currentText() or profile.database or ""
        self.view_page.ctx_label.setText(
            f"{profile.display_name} · {database} · {schema or '默认'}"
             if profile.is_postgres else
             f"{profile.display_name} · {schema or '默认'}")

        def fetch():
            return [v for v in self._metadata.schema_tables(profile, schema, database)
                    if v.get("type") == "VIEW"]

        def done(rows: list[dict]) -> None:
            self.view_page.load_views(profile.id, schema, rows)

        run_async(fetch, done, lambda err: self.view_page.ctx_label.setText(
            f"读取视图失败：{err}"))

    def _reload_routine_browse(self, profile=None, schema: str = "",
                               database: str = "") -> None:
        """按当前连接/库刷新「函数」对象页列表（一次批查，无 N+1）。"""
        profile = profile or self._current_profile()
        if profile is None:
            self.routine_page.clear()
            self.routine_page.ctx_label.setText("")
            return
        if profile.is_postgres:
            schema = schema or "public"
            database = database or profile.database or ""
        else:
            schema = schema or self.schema_combo.currentText() or profile.database or ""
        self.routine_page.ctx_label.setText(
            f"{profile.display_name} · {database} · {schema or '默认'}"
             if profile.is_postgres else
             f"{profile.display_name} · {schema or '默认'}")

        def fetch():
            if profile.is_postgres:
                return self._metadata.routines_in_database(profile, database, schema)
            return self._metadata.routines(profile, schema)

        def done(rows: list[dict]) -> None:
            self.routine_page.load_routines(profile.id, schema, rows)

        run_async(fetch, done, lambda err: self.routine_page.ctx_label.setText(
            f"读取函数失败：{err}"))

    def _reload_trigger_browse(self, profile=None, schema: str = "",
                               database: str = "") -> None:
        """按当前连接/库刷新「触发器」对象页列表（一次批查，无 N+1）。"""
        profile = profile or self._current_profile()
        if profile is None:
            self.trigger_page.clear()
            self.trigger_page.ctx_label.setText("")
            return
        schema = schema or self.schema_combo.currentText() or profile.database or ""
        self.trigger_page.ctx_label.setText(
            f"{profile.display_name} · {database} · {schema or '默认'}"
             if profile.is_postgres else
             f"{profile.display_name} · {schema or '默认'}")

        def fetch():
            return self._metadata.triggers(profile, schema)

        def done(rows: list[dict]) -> None:
            self.trigger_page.load_triggers(profile.id, schema, rows)

        run_async(fetch, done, lambda err: self.trigger_page.ctx_label.setText(
            f"读取触发器失败：{err}"))

    # ---- 序列（PostgreSQL「其它」领域） ----
    def _reload_sequence_browse(self, profile=None, database: str = "",
                                schema: str = "") -> None:
        """按当前连接/库刷新「序列」对象页列表（PG 专属，一次批查，无 N+1）。"""
        profile = profile or self._current_profile()
        if profile is None:
            self.sequence_page.clear()
            self.sequence_page.ctx_label.setText("")
            return
        # 刷新/DDL 完成后的重载必须保持序列页当前库/模式，不能退回连接初始库。
        database = database or getattr(self.sequence_page, "_database", None) or ""
        schema = schema or getattr(self.sequence_page, "_schema", None) or ""
        if self._object_context and self._object_context[0] == profile.id:
            database = database or self._object_context[1]
            schema = schema or self._object_context[2]
        database = database or profile.database or self.schema_combo.currentText() or ""
        schema = schema or self.schema_combo.currentText() or profile.database or ""
        self.sequence_page.ctx_label.setText(
            f"{profile.display_name} · {database} · {schema or '默认'}")

        def fetch():
            if not profile.is_postgres:
                return []
            return self._metadata.sequences_in_database(profile, database, schema)

        def done(rows: list[dict]) -> None:
            if profile.is_postgres:
                self.sequence_page.load_sequences(profile.id, database, schema, rows)
            else:
                self.sequence_page.clear()

        def error(err: str) -> None:
            # 错误不占用序列页操作栏，保留当前上下文并用统一错误框提示。
            self.sequence_page.ctx_label.setText(
                f"{profile.display_name} · {database} · {schema or '默认'}")
            from magiccat.utils.errors import clean_java_error

            QMessageBox.critical(self, "读取序列失败", clean_java_error(err))

        run_async(fetch, done, error)

    def _resolve_pg_database_schema(self) -> tuple[str, str] | None:
        """取当前连接/库的 (database, schema)。PG 下二者来自下拉；非 PG 返回 None。"""
        profile = self._current_profile()
        if profile is None or not profile.is_postgres:
            return None
        database = profile.database or self.schema_combo.currentText() or ""
        # MySQL 的 schema_combo 存的是库；PG 下尽可能取“模式”文本（若下拉存 schema）
        schema = self.schema_combo.currentText() or database or ""
        return database, schema

    def _design_sequence(self, profile_id: str, database: str, schema: str,
                         name: str) -> None:
        """设计序列（对象页双击/设计）：打开序列编辑对话框。"""
        from magiccat.ui.sequence_dialog import SequenceDialog

        profile = self._connections.get(profile_id)
        if profile is None or not profile.is_postgres:
            return
        data = {}
        try:
            rows = self._metadata.sequences_in_database(profile, database, schema)
            data = next((r for r in rows if r.get("name") == name), {})
        except Exception:  # noqa: BLE001
            data = {}
        dlg = SequenceDialog(schema, name=name, mode="edit", data=data, parent=self)
        dlg.exec()

    def _new_sequence(self) -> None:
        """新建序列：PG 下弹新建序列对话框。"""
        profile = self._current_profile()
        if profile is None or not profile.is_postgres:
            QMessageBox.information(self, "新建序列", "仅 PostgreSQL 支持序列。")
            return
        schema = self.schema_combo.currentText() or profile.database or ""
        from magiccat.ui.sequence_dialog import SequenceDialog

        dlg = SequenceDialog(schema, name="new_sequence", mode="create", parent=self)
        if dlg.exec():
            self._run_sequence_sql(profile, dlg.sql(), "新建序列")

    def _delete_sequence(self, profile_id: str, database: str, schema: str,
                         name: str) -> None:
        """删除序列：确认后 DROP SEQUENCE，并刷新序列对象页。"""
        from magiccat.services.query_service import QueryService

        profile = self._connections.get(profile_id)
        if profile is None:
            return
        sql = f'DROP SEQUENCE IF EXISTS "{schema}"."{name}"'
        if QMessageBox.question(
                self, "删除序列",
                f"确定删除序列 `{schema}`.{name}？\n\n{sql}",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        def done(results: list[dict]) -> None:
            errors = [r for r in results if r.get("kind") == "error"]
            if errors:
                QMessageBox.warning(self, "删除序列", errors[0]["message"])
                return
            self._reload_sequence_browse(profile, database, schema)
            self._status(f"序列已删除：{schema}.{name}", 4000)

        run_async(lambda: QueryService(self._connections).execute(profile, sql),
                  done, lambda err: QMessageBox.critical(self, "删除序列", err))

    def _run_sequence_sql(self, profile, sql: str, verb: str) -> None:
        """执行序列 SQL（CREATE/ALTER），成功后刷新序列对象页。"""
        from magiccat.services.query_service import QueryService

        def done(results: list[dict]) -> None:
            errors = [r for r in results if r.get("kind") == "error"]
            if errors:
                QMessageBox.warning(self, verb, errors[0]["message"])
                return
            self._status(f"{verb}成功", 4000)
            self._reload_sequence_browse(profile)

        run_async(lambda: QueryService(self._connections).execute(profile, sql),
                  done, lambda err: QMessageBox.critical(self, verb, err))

    def _query_btn(self, text: str, handler, bar: QHBoxLayout):
        from PySide6.QtWidgets import QPushButton

        btn = QPushButton(text)
        btn.clicked.connect(handler)
        bar.addWidget(btn)
        return btn

    def _build_explorer_dock(self) -> None:
        self.explorer = ObjectExplorer(self._connections, self._metadata)
        self.explorer.open_table_requested.connect(self._on_open_table)
        self.explorer.design_table_requested.connect(self._on_design_table)
        self.explorer.er_database_requested.connect(self._on_er_database)
        self.explorer.create_table_requested.connect(self._on_create_table)
        self.explorer.open_saved_query.connect(self._open_saved_query)
        self.explorer.create_routine_entry.connect(self._on_create_routine)
        self.explorer.open_routine_sql.connect(self._open_routine_sql)
        self.explorer.selection_info_requested.connect(self._on_selection_info)
        self.explorer.object_context_selected.connect(self._on_object_context_selected)
        self.explorer.new_query_requested.connect(self._on_new_query_from_explorer)
        self.explorer.profile_activated.connect(self._set_current_profile)
        dock = QDockWidget("对象浏览器", self)
        dock.setObjectName("explorer_dock")
        dock.setMinimumWidth(180)
        dock.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Expanding)

        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(3, 3, 3, 3)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("过滤 连接/库/表…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.explorer.apply_name_filter)
        box.addWidget(self.filter_edit)
        box.addWidget(self.explorer, 1)
        dock.setWidget(container)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.explorer_dock = dock
        self.explorer.load_profiles()

    def _build_info_dock(self) -> None:
        from magiccat.ui.connection_info_panel import ConnectionInfoPanel

        self.info_panel = ConnectionInfoPanel(self._connections, self._metadata)
        dock = QDockWidget("信息", self)
        dock.setObjectName("info_dock")
        dock.setMinimumWidth(160)
        dock.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Expanding)
        dock.setWidget(self.info_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.info_dock = dock

    def _build_quick_toolbar(self) -> None:
        """对标 Navicat 顶部快速访问栏（图标+文字在下）；仅放已实现功能，
        未实现的（其它/BI）不放置。"""
        from magiccat.ui.icons import icon

        toolbar = QToolBar("快速访问")
        toolbar.setObjectName("quick_toolbar")
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.addToolBar(toolbar)
        self._domain_action_group = QActionGroup(self)
        self._domain_action_group.setExclusive(True)
        self._domain_actions: dict[str, QAction] = {}

        def quick(text: str, kind: str, handler) -> None:
            act = QAction(icon(kind), text, self)
            act.setToolTip(text)
            act.triggered.connect(handler)
            toolbar.addAction(act)

        def quick_domain(text: str, kind: str, domain: str) -> None:
            act = QAction(icon(kind), text, self)
            act.setToolTip(text)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked=False, d=domain: self._show_domain(d))
            self._domain_action_group.addAction(act)
            self._domain_actions[domain] = act
            toolbar.addAction(act)

        quick("连接", "connection", self._add_connection)
        quick("新建查询", "new_query", self._new_editor)
        toolbar.addSeparator()
        quick_domain("表", "table", "tables")
        quick_domain("视图", "view", "views")
        quick_domain("函数", "function", "routines")
        toolbar.addSeparator()
        quick("用户", "user", self._quick_user)
        toolbar.addSeparator()
        quick_domain("查询", "query", "queries")
        self._add_other_button(toolbar)
        self._set_domain_action("tables")

    def _set_domain_action(self, domain: str) -> None:
        """更新窗口级当前功能域，并同步顶部动作的选中态。"""
        self._current_domain = domain
        actions = getattr(self, "_domain_actions", None)
        if actions:
            action = actions.get(domain)
            if action is not None:
                action.setChecked(True)
            else:
                for candidate in actions.values():
                    candidate.setChecked(False)
        other_button = getattr(self, "_other_domain_button", None)
        if other_button is not None:
            other_button.setChecked(domain == "sequences")

    def _add_other_button(self, toolbar) -> None:
        """「其它」领域（永驻）：下拉菜单按数据库类型增减。
        - PostgreSQL：序列（等）；
        - MySQL：暂无可用的「其它」项（无序列/类型等），菜单为空。
        菜单在点击展开时（aboutToShow）按当前连接实时重建，避免切换事件遗漏导致空菜单。
        """
        from PySide6.QtWidgets import QMenu, QToolButton

        from magiccat.ui.icons import icon

        btn = QToolButton()
        btn.setText("其它")
        btn.setIcon(icon("other"))
        btn.setCheckable(True)
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(btn)
        btn.setMenu(menu)
        toolbar.addWidget(btn)
        self._other_domain_button = btn

        def rebuild() -> None:
            menu.clear()
            profile = self._current_profile()
            if profile is not None and profile.is_postgres:
                act_seq = menu.addAction("序列")
                act_seq.triggered.connect(lambda: self._show_other_sequence())

        # 每次点开菜单时按当前连接实时重建（兼容：连接经对象树打开、combo 未变等场景）
        menu.aboutToShow.connect(rebuild)
        rebuild()

    def _show_other_sequence(self) -> None:
        """「其它」→ 序列：切到序列对象页并展示当前库序列。"""
        database = schema = ""
        profile = self._current_profile()
        if self._object_context and (profile is None or self._object_context[0] == profile.id):
            _profile_id, database, schema = self._object_context
        self._show_domain("sequences", schema=schema, database=database)

    def _quick_user(self) -> None:
        """用户：打开用户管理面板（对标 Navicat）。"""
        profile = self._current_profile()
        if profile is None:
            QMessageBox.information(self, "用户", "请先选择连接。")
            return
        for i in range(self.editor_tabs.count()):
            w = self.editor_tabs.widget(i)
            if getattr(w, "tab_key", None) == "user-manager" and w.profile.id == profile.id:
                self.editor_tabs.setCurrentIndex(i)
                return
        from magiccat.ui.user_manager import UserManagerWidget

        widget = UserManagerWidget(profile, self._connections)
        index = self.editor_tabs.addTab(widget, f"用户 · {profile.display_name}")
        self.editor_tabs.setCurrentIndex(index)
        self._status(f"已打开用户管理（{profile.display_name}）")

    def _resolve_current_schema(self) -> str | None:
        """取当前连接的默认库；无则让用户从库列表选。返回 schema 或 None。"""
        profile = self._current_profile()
        if profile is None:
            QMessageBox.information(self, "快速创建", "请先选择连接。")
            return None
        if profile.database:
            return profile.database
        try:
            dbs = [d["name"] for d in self._metadata.databases(profile)]
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "快速创建", f"读取库列表失败：{exc}")
            return None
        name, ok = QInputDialog.getItem(self, "快速创建", "选择库：", dbs, 0, False)
        return name if ok and name else None

    def _quick_create_object(self, what: str) -> None:
        schema = self._resolve_current_schema()
        if not schema:
            return
        profile = self._current_profile()
        if what == "table":
            name, ok = QInputDialog.getText(self, "新建表", f"在 `{schema}` 中新建表：", "new_table")
            name = (name or "").strip()
            if ok and name:
                from magiccat.ui.table_designer import TableDesignerDialog

                TableDesignerDialog(profile, schema, name, self._connections,
                                    self, new_table=True).exec()
                self.explorer.refresh_schema(profile.id, schema)
        elif what == "view":
            name, ok = QInputDialog.getText(self, "新建视图", f"在 `{schema}` 中新建视图：", "v_new")
            name = (name or "").strip()
            if ok and name:
                editor = self._new_editor()
                editor.setPlainText(
                    f"CREATE VIEW `{schema.replace('`', '``')}`.`{name.replace('`', '``')}` AS\n"
                    "SELECT ...  -- 填写查询")
                index = self.editor_tabs.indexOf(editor)
                self.editor_tabs.setTabText(index, name + "（视图）")
                self._status("新建视图模板已生成：填写 SELECT 后「运行」创建", 8000)
        elif what == "routine":
            self._on_create_routine(profile.id, schema)

    def _build_actions(self) -> None:
        menu_conn = self.menuBar().addMenu("连接(&C)")
        act_add = menu_conn.addAction("新增连接…")
        act_add.triggered.connect(self._add_connection)
        act_test = menu_conn.addAction("测试连接…")
        act_test.triggered.connect(self._test_prompt)

        menu_query = self.menuBar().addMenu("查询(&Q)")
        self.act_new = menu_query.addAction("新建查询\tCtrl+T")
        self.act_new.setShortcut("Ctrl+T")
        self.act_new.triggered.connect(self._new_editor)
        self.act_run = menu_query.addAction("运行\tF5")
        self.act_run.setShortcut("F5")
        self.act_run.triggered.connect(self._run_current)
        self.act_cancel = menu_query.addAction("取消执行")
        self.act_cancel.setEnabled(False)
        self.act_cancel.triggered.connect(self._cancel_execution)
        menu_query.addSeparator()
        self.act_format = menu_query.addAction("美化 SQL")
        self.act_format.triggered.connect(self._format_sql)
        self.act_explain = menu_query.addAction("EXPLAIN 当前语句")
        self.act_explain.triggered.connect(self._explain_current)
        act_history = menu_query.addAction("最近执行的 SQL…")
        act_history.triggered.connect(self._insert_history)
        act_snippets = menu_query.addAction("SQL 收藏…")
        act_snippets.triggered.connect(self._open_snippets)
        self.act_save_query = menu_query.addAction("保存查询…\tCtrl+Shift+S")
        self.act_save_query.setShortcut("Ctrl+Shift+S")
        self.act_save_query.triggered.connect(self._save_query_dialog)
        act_close = menu_query.addAction("关闭当前标签\tCtrl+W")
        act_close.setShortcut("Ctrl+W")
        act_close.triggered.connect(lambda: self._close_editor_tab(self.editor_tabs.currentIndex()))

        menu_tools = self.menuBar().addMenu("工具(&T)")
        act_import = menu_tools.addAction("导入 CSV 到表…")
        act_import.triggered.connect(self._open_import_dialog)
        act_backup = menu_tools.addAction("备份数据库为 SQL…")
        act_backup.triggered.connect(self._open_backup_dialog)
        # 计划任务入口已暂隐（对应 Navicat 自动运行，本轮隐藏）
        act_copy = menu_tools.addAction("复制表（数据传输）…")
        act_copy.triggered.connect(self._open_copy_dialog)
        act_restore = menu_tools.addAction("执行 SQL 脚本（恢复）…")
        act_restore.triggered.connect(self._open_restore_dialog)
        menu_tools.addSeparator()
        act_environment = menu_tools.addAction("环境…")
        act_environment.triggered.connect(self._open_environment)

        menu_view = self.menuBar().addMenu("视图(&V)")
        self.act_dark = menu_view.addAction("深色主题")
        self.act_dark.setCheckable(True)
        self.act_dark.setChecked(self._settings.get("theme", "light") == "dark")
        self.act_dark.triggered.connect(self._toggle_theme)

        menu_help = self.menuBar().addMenu("帮助(&H)")
        act_shortcuts = menu_help.addAction("快捷键说明…")
        act_shortcuts.triggered.connect(self._show_shortcuts)
        act_logdir = menu_help.addAction("打开日志目录…")
        act_logdir.triggered.connect(self._open_log_dir)
        act_about = menu_help.addAction("关于 MagicCat…")
        act_about.triggered.connect(self._about)

    # ---- 连接选择（查询领域「当前连接选择」下拉；亦由对象树激活跟手） ----
    def _reload_connection_combo(self) -> None:
        from magiccat.ui.profile_combo import populate_profile_combo

        populate_profile_combo(self.profile_combo, self._connections.profiles,
                               "<未选择连接>")

    def _open_environment(self) -> None:
        EnvironmentDialog(self).exec()

    def _set_current_profile(self, profile_id: str) -> None:
        """对象树激活某连接/对象 → 使之成为当前连接（跟手），并同步查询领域的连接下拉。"""
        idx = self.profile_combo.findData(profile_id)
        if idx >= 0 and self.profile_combo.currentData() != profile_id:
            self.profile_combo.setCurrentIndex(idx)  # 触发 _on_profile_selected
        elif idx >= 0:
            # 已是当前：刷新展示/信息面板与库下拉
            self._on_profile_selected()

    def _current_profile(self) -> ConnectionProfile | None:
        # 查询标签激活时：当前连接取自该标签自己的连接下拉（影响不扩散）
        ws = self._current_query_ws()
        if ws is not None and ws.profile_combo.currentData():
            pid = ws.profile_combo.currentData()
            return self._connections.get(pid)
        # 否则（对象页浏览）用全局当前连接（树跟手）
        pid = self.profile_combo.currentData()
        if not pid:
            return None
        return self._connections.get(pid)

    @property
    def result_panel(self):
        ws = self._current_query_ws()
        return ws.result_panel if ws is not None else None

    def _on_profile_selected(self) -> None:
        # 这是对象浏览条的全局连接选择。查询标签激活时，_current_profile()
        # 属于该标签，不能拿它覆盖树跟手的对象浏览上下文。
        profile = self._connections.get(self.profile_combo.currentData())
        self.setWindowTitle(f"MagicCat — {profile.display_name}" if profile else "MagicCat")
        self._status(f"当前连接：{profile.name if profile else '未选择'}")
        self.info_panel.show_profile(self.profile_combo.currentData() if profile else None)
        self._reload_schema_combo(profile)
        self._reload_query_browse()

    def _reload_schema_combo(self, profile) -> None:
        self.schema_combo.blockSignals(True)
        self.schema_combo.clear()
        self.schema_combo.setEnabled(False)
        self.schema_combo.blockSignals(False)
        if profile is None:
            return
        self.schema_combo.setEnabled(True)

        def fetch() -> list[str]:
            return [d["name"] for d in self._metadata.databases(profile)
                    if d["name"] not in _SYSTEM_SCHEMAS]

        def done(dbs: list[str]) -> None:
            self.schema_combo.blockSignals(True)
            self.schema_combo.clear()
            self.schema_combo.addItems(dbs)
            if profile.database and profile.database in dbs:
                self.schema_combo.setCurrentText(profile.database)
            self.schema_combo.blockSignals(False)
            self._reload_query_browse()

        run_async(fetch, done, lambda err: logger.warning("加载库下拉失败: %s", err))
        if profile is not None:
            self._update_completion_words(profile)

    def _update_completion_words(self, profile: ConnectionProfile, ws=None) -> None:
        """构建当前 Catalog/Schema 的上下文补全数据（表+视图+列，一次批查）。"""
        # 捕获目标工作区；异步回调不能再用“当前标签”，否则切换标签后会串补全数据。
        target_ws = ws if ws is not None else self._current_query_ws()
        target_profile_id = (target_ws.profile_combo.currentData()
                             if target_ws is not None else None)
        if target_ws is not None and target_profile_id not in (None, profile.id):
            # 显式请求另一个工作区时，绝不把结果写进当前标签。
            return
        if target_ws is not None:
            database = (target_ws.database_combo.currentText() or profile.database or "").strip()
            schema = ((target_ws.selected_schema() or "public")
                      if profile.is_postgres else None)
        elif profile.is_postgres:
            # 对象浏览条的全局下拉只有 Catalog；对象页补全默认 public。
            database = (self.schema_combo.currentText() or profile.database or "").strip()
            schema = "public"
        else:
            # MySQL 的信息层参数名仍叫 schema，但它实际表示 catalog/database。
            database = (self.schema_combo.currentText() or profile.database or "").strip()
            schema = database
        meta = self._metadata

        def fetch() -> dict:
            # 一次批查当前 schema 的表/视图 + 所有列（无 N+1）
            tables = []
            if profile.is_postgres:
                t_rows = meta.schema_tables_in_database(profile, database, schema or "public")
                c_rows = meta.schema_columns_in_database(profile, database, schema or "public")
            else:
                t_rows = meta.schema_tables(profile, schema or database)
                c_rows = meta.schema_columns(profile, schema or database)
            for t in t_rows:
                name = t.get("name")
                if name:
                    kind = "view" if str(t.get("type", "")).upper() == "VIEW" else "table"
                    tables.append({"name": name, "kind": kind})
            columns: dict[str, list[str]] = {}
            for c in c_rows:
                tn = c.get("table_name")
                cn = c.get("name")
                if tn and cn:
                    columns.setdefault(tn, []).append(cn)
            return {"tables": tables, "columns": columns}

        def done(data: dict) -> None:
            if target_ws is not None and target_profile_id == profile.id:
                # 上一次上下文的查询可能晚于本次返回，丢弃其结果。
                if target_ws.profile_combo.currentData() != profile.id:
                    return
                current_database = (target_ws.database_combo.currentText() or "").strip()
                current_schema = target_ws.selected_schema() or ("public" if profile.is_postgres else None)
                expected_schema = schema or ("public" if profile.is_postgres else None)
                if current_database != database or current_schema != expected_schema:
                    return
            editor = target_ws if target_ws is not None else self._active_editor()
            if editor is not None and hasattr(editor, "set_completion_data"):
                editor.set_completion_data(data)
            n = len(data.get("tables", []))
            self._status(f"对象提示已更新（{n} 个表/视图）")

        run_async(fetch, done, lambda err: logger.warning("加载补全对象失败: %s", err))

    # ---- 编辑器管理 ----
    def _make_editor(self):
        import os as _os

        if _os.environ.get("MAGICCAT_EDITOR") == "plain":
            from magiccat.ui.editor import SqlEditorWidget

            return SqlEditorWidget()
        return MonacoEditorWidget()

    def _capture_new_query_context(self) -> tuple[str | None, str, str | None, bool]:
        """拍摄新查询的初始化上下文；创建后不再随树选中变化。"""
        # 普通“新建查询”优先继承左侧树最近激活的元素；这是一次性初始化，
        # 后续树选中不会再改写新标签。
        tree_context = self._tree_query_context()
        if tree_context is not None:
            return tree_context

        active = self._current_query_ws()
        if active is not None:
            profile_id = active.profile_combo.currentData()
            profile = self._connections.get(profile_id)
            if profile is not None:
                catalog = (active.selected_catalog()
                           or getattr(active, "_pending_database", "")
                           or profile.database or "").strip()
                if profile.is_postgres:
                    pending = getattr(active, "_pending_schema", None)
                    if pending is not None:
                        return profile_id, catalog, pending or None, True
                    if active.schema_combo.isEnabled():
                        return profile_id, catalog, active.selected_schema(), True
                return profile_id, catalog, None, False

        profile_id = self.profile_combo.currentData()
        profile = self._connections.get(profile_id)
        if profile is None:
            return None, "", None, False
        catalog = (self.schema_combo.currentText() or profile.database or "").strip()
        # 对象浏览条只有全局 Catalog 下拉；PG 的 Schema 在新查询中按默认 public
        # 处理，右键模式级新建则由显式上下文覆盖。
        return profile_id, catalog, None, False

    def _tree_query_context(self) -> tuple[str, str, str | None, bool] | None:
        """读取左侧树当前元素的查询初始化上下文。

        返回 ``(profile_id, catalog, schema, schema_explicit)``。数据库节点只
        确定 Catalog，模式节点及其下对象同时确定 Schema；MySQL 的 Schema 为
        ``None``。分组、分类或没有可归属连接的节点不提供上下文。
        """
        explorer = getattr(self, "explorer", None)
        item = explorer.currentItem() if explorer is not None else None
        if item is None:
            return None
        info = item.data(0, Qt.UserRole) or {}
        kind = info.get("kind")
        data = info.get("data", {})
        if kind in ("group", "placeholder", "error"):
            return None
        profile = explorer._profile_of(item)
        if profile is None:
            return None
        if kind == "profile":
            return profile.id, (profile.database or "").strip(), None, False
        if kind == "database":
            return profile.id, str(data.get("schema", "")).strip(), None, profile.is_postgres
        if kind == "schema":
            return (profile.id, str(data.get("database", "")).strip(),
                    str(data.get("schema", "")).strip(), True)
        catalog = str(explorer._database_of(item) or "").strip()
        schema = str(explorer._schema_of(item) or "").strip()
        if not catalog and not schema:
            return None
        if profile.is_postgres:
            return profile.id, catalog, schema or None, True
        return profile.id, catalog or schema, None, False

    def _new_editor_with_context(
        self,
        profile_id: str | None,
        catalog: str = "",
        schema: str | None = None,
        schema_explicit: bool = False,
    ):
        from magiccat.ui.query_workspace import QueryWorkspace

        self._tab_seq += 1
        editor = self._make_editor()
        ws = QueryWorkspace(editor)
        # 必须在异步下拉加载前写入 pending，避免回调先返回时丢失初始化定位。
        if profile_id:
            ws._pending_database = (catalog or "").strip()
            if schema_explicit:
                ws._pending_schema = (schema or "").strip()
        ws.run_requested.connect(self._run_current)
        ws.stop_requested.connect(self._cancel_execution)
        ws.explain_requested.connect(self._explain_current)
        ws.save_requested.connect(self._save_query_dialog)
        ws.format_requested.connect(self._format_sql)
        ws.snippet_requested.connect(lambda: self._insert_snippet(ws))
        ws.ask_ai_requested.connect(lambda: self._ask_ai(ws))
        # 先填充初始连接/Catalog/Schema；初始化期间不触发工作区切换回调，
        # 否则 profile_combo 从占位项切到目标连接会清空右键传入的 pending 值。
        self._populate_ws_combos(ws, profile=profile_id)
        ws.profile_combo.currentIndexChanged.connect(
            lambda _i: self._on_ws_profile_changed(ws))
        ws.database_combo.currentIndexChanged.connect(
            lambda _i: self._on_ws_database_changed(ws))
        ws.schema_combo.currentIndexChanged.connect(
            lambda _i: self._on_ws_schema_changed(ws))
        ws.editor.workspace = ws
        index = self.editor_tabs.addTab(ws, f"查询 {self._tab_seq}")
        self.editor_tabs.setCurrentIndex(index)
        ws.editor.setFocus()
        return ws

    def _new_editor(self, _checked: bool = False):
        """新建查询：只在创建瞬间继承当前连接/Catalog/Schema。"""
        profile_id, catalog, schema, schema_explicit = self._capture_new_query_context()
        return self._new_editor_with_context(
            profile_id, catalog, schema, schema_explicit)

    def _populate_ws_combos(self, ws, profile: str | None = None) -> None:
        """填充查询工作区的连接、Catalog、Schema（影响只在本标签）。"""
        from magiccat.ui.profile_combo import populate_profile_combo

        populate_profile_combo(ws.profile_combo, self._connections.profiles,
                               "<未选择连接>")
        if profile:
            idx = ws.profile_combo.findData(profile)
            if idx >= 0:
                ws.profile_combo.setCurrentIndex(idx)
            prof = self._connections.get(profile)
            if prof is not None:
                self._reload_ws_context(ws, prof)

    def _reload_ws_schema_combo(self, ws, profile) -> None:
        """兼容旧调用名：重载工作区 Catalog，并按产品加载 Schema。"""
        self._reload_ws_context(ws, profile)

    def _reload_ws_context(self, ws, profile) -> None:
        """加载一个查询标签自己的 Catalog/Schema 下拉，不影响其它标签。"""
        ws.set_schema_visible(profile.is_postgres)
        ws.database_combo.blockSignals(True)
        ws.database_combo.clear()
        ws.database_combo.setEnabled(False)
        ws.database_combo.blockSignals(False)
        ws.schema_combo.blockSignals(True)
        ws.schema_combo.clear()
        # MySQL 的 JDBC schema 永远为 null；在 UI 中禁用模式选择，避免产生假上下文。
        ws.schema_combo.setEnabled(False)
        ws.schema_combo.blockSignals(False)

        def fetch() -> list[str]:
            return [d["name"] for d in self._metadata.databases(profile)
                    if d["name"] not in _SYSTEM_SCHEMAS]

        def done(dbs: list[str]) -> None:
            # 连接切换期间旧请求可能晚返回，不能覆盖新连接的上下文。
            if ws.profile_combo.currentData() != profile.id:
                return
            ws.database_combo.blockSignals(True)
            ws.database_combo.clear()
            from magiccat.ui.icons import icon

            database_icon = icon("database")
            for name in dbs:
                ws.database_combo.addItem(database_icon, name)
            desired = ws._pending_database or profile.database or ""
            if profile.is_postgres and "postgres" in dbs and desired not in dbs:
                desired = "postgres"
            if desired not in dbs and dbs:
                desired = dbs[0]
            if desired:
                ws.database_combo.setCurrentText(desired)
            ws._pending_database = ""
            ws.database_combo.blockSignals(False)
            ws.database_combo.setEnabled(True)
            if profile.is_postgres and desired:
                self._reload_ws_schemas(ws, profile, desired)
            else:
                self._clear_ws_schema(ws)
                self._update_completion_words(profile, ws)

        run_async(fetch, done, lambda err: logger.warning("加载工作区 Catalog 下拉失败: %s", err))

    def _reload_ws_schemas(self, ws, profile, database: str) -> None:
        """PostgreSQL/GaussDB：按当前 Catalog 加载 Schema 列表。"""
        ws.set_schema_visible(True)
        ws.schema_combo.blockSignals(True)
        ws.schema_combo.clear()
        ws.schema_combo.setEnabled(False)
        ws.schema_combo.blockSignals(False)

        def fetch() -> list[str]:
            return [s["name"] for s in self._metadata.schemas(profile, database)
                    if s.get("name")]

        def done(schemas: list[str]) -> None:
            if ws.profile_combo.currentData() != profile.id:
                return
            if (ws.database_combo.currentText() or "").strip() != database:
                return
            names = list(dict.fromkeys(schemas))
            ws.schema_combo.blockSignals(True)
            ws.schema_combo.clear()
            from magiccat.ui.icons import icon

            schema_icon = icon("schema")
            for name in names:
                ws.schema_combo.addItem(schema_icon, name)
            # PG/GaussDB 默认模式统一为 public；对象树定位到的模式优先。
            preferred = ws._pending_schema
            if preferred == "":
                # 数据库级右键新建查询：Catalog 已确定，但 Schema 保持空选。
                ws.schema_combo.setCurrentIndex(-1)
            elif preferred and preferred in names:
                ws.schema_combo.setCurrentText(preferred)
            elif "public" in names:
                ws.schema_combo.setCurrentText("public")
            elif names:
                ws.schema_combo.setCurrentIndex(0)
            ws._pending_schema = None
            ws.schema_combo.blockSignals(False)
            ws.schema_combo.setEnabled(True)
            self._update_completion_words(profile, ws)

        run_async(fetch, done,
                  lambda err: logger.warning("加载工作区 Schema 下拉失败: %s", err))

    @staticmethod
    def _clear_ws_schema(ws) -> None:
        ws.set_schema_visible(False)
        ws.schema_combo.blockSignals(True)
        ws.schema_combo.clear()
        ws.schema_combo.setEnabled(False)
        ws.schema_combo.blockSignals(False)

    def _on_ws_profile_changed(self, ws) -> None:
        """某查询工作区切换连接 → 重载该工作区自己的 Catalog/Schema。"""
        prof = self._connections.get(ws.profile_combo.currentData())
        if prof is not None:
            ws.clear_pending_context()
            self._reload_ws_context(ws, prof)
        else:
            ws.clear_pending_context()
            ws.database_combo.blockSignals(True)
            ws.database_combo.clear()
            ws.database_combo.setEnabled(False)
            ws.database_combo.blockSignals(False)
            self._clear_ws_schema(ws)

    def _on_ws_database_changed(self, ws) -> None:
        profile = self._connections.get(ws.profile_combo.currentData())
        if profile is None:
            return
        database = (ws.database_combo.currentText() or "").strip()
        if profile.is_postgres and database:
            self._reload_ws_schemas(ws, profile, database)
        else:
            self._clear_ws_schema(ws)
            self._update_completion_words(profile, ws)

    def _on_ws_schema_changed(self, ws) -> None:
        profile = self._connections.get(ws.profile_combo.currentData())
        if profile is not None:
            self._update_completion_words(profile, ws)

    @staticmethod
    def _workspace_context(ws, profile: ConnectionProfile) -> tuple[str, str | None]:
        """返回当前查询标签的 (JDBC catalog, JDBC schema)。"""
        catalog = (ws.database_combo.currentText()
                   or getattr(ws, "_pending_database", "")
                   or profile.database or "").strip()
        if not profile.is_postgres:
            # MySQL/MariaDB 只有 catalog；schema 必须保持 SQL NULL 语义。
            return catalog, None
        pending = getattr(ws, "_pending_schema", None)
        # 对象树按 schema 定位时，即使下拉仍在异步加载，也优先保留该待选值。
        if pending:
            return catalog, pending
        # 异步加载尚未完成时按 PG 默认模式执行；已加载但用户/库级右键
        # 清空时 currentIndex() 为 -1，保留空 Schema，不擅自补 public。
        if not ws.schema_combo.isEnabled():
            return catalog, "public"
        selected = ws.selected_schema()
        if selected is not None:
            return catalog, selected
        return catalog, None

    def _current_query_ws(self):
        from magiccat.ui.query_workspace import QueryWorkspace

        w = self.editor_tabs.currentWidget()
        return w if isinstance(w, QueryWorkspace) else None

    def _open_object_tab(self, tab_key: str, title: str, content: str):
        """打开一个对象标签并保证单例：同 tab_key 已开 → 定位到该标签；
        否则新建编辑器标签并写入内容。返回（可能已存在的）编辑器。"""
        for i in range(self.editor_tabs.count()):
            w = self.editor_tabs.widget(i)
            if getattr(w, "tab_key", None) == tab_key:
                self.editor_tabs.setCurrentIndex(i)
                return w
        ws = self._new_editor()
        ws.tab_key = tab_key
        ws.setPlainText(content)
        self.editor_tabs.setTabText(self.editor_tabs.indexOf(ws), title)
        return ws

    def _active_editor(self):
        return self._current_query_ws()

    def _close_editor_tab(self, index: int) -> None:
        if index <= 0:  # 第 0 页「对象」为固定占位，不可关闭
            return
        if self.editor_tabs.count() <= 1:
            return
        self.editor_tabs.removeTab(index)

    # ---- 执行流 ----
    def _run_current(self) -> None:
        self._run_sql()

    def _run_sql(self) -> None:
        ws = self._current_query_ws()
        if ws is None:
            return
        profile = self._current_profile()
        if profile is None:
            QMessageBox.information(self, "执行 SQL", "请先在工具栏选择要执行的连接。")
            return
        editor = ws.editor
        sql = ws.sql_for_run()
        if not sql.strip():
            self._status("无可执行内容：请输入 SQL")
            return
        catalog, schema = self._workspace_context(ws, profile)
        self._status(f"正在执行（{profile.name}）…")
        ws.result_panel.append_message(f"──── 执行 · {profile.name} · {sql}")
        if ws.status_label is not None:
            ws.set_status(f"正在执行（{profile.name}）…")
        # 支持多标签并行：每次执行独立入池，结果写回对应工作区
        self._running += 1
        self.act_cancel.setEnabled(True)
        run_async(
            lambda: self._query.execute(profile, sql, database=catalog, schema=schema),
            lambda results: self._on_executed(results, ws, editor),
            lambda err: self._on_exec_error(err, ws))

    def _cancel_execution(self) -> None:
        count = self._query.cancel_all()
        self._status(f"正在取消 {count} 个执行中的查询…")
        if count == 0:
            self.act_cancel.setEnabled(False)

    def _on_executed(self, results: list[dict], ws=None, editor=None) -> None:
        self._running = max(0, self._running - 1)
        self.act_cancel.setEnabled(self._running > 0)
        if ws is not None:
            ws.result_panel.show_results(results)
        cancelled = any(r.get("cancelled") for r in results)
        errors = [r for r in results if r.get("kind") == "error"]
        total = round(sum(float(r.get("time_ms", 0)) for r in results), 1)
        if cancelled:
            self._status(f"执行已取消（{total} ms）", 5000)
        elif errors:
            self._status(f"完成，{len(errors)}/{len(results)} 条语句失败（共 {total} ms）", 8000)
        else:
            self._status(f"完成：{len(results)} 条语句全部成功（共 {total} ms）", 5000)
        if editor is not None:
            self._history.push(editor.all_text())

    def _on_exec_error(self, err: str, ws=None) -> None:
        self._running = max(0, self._running - 1)
        self.act_cancel.setEnabled(self._running > 0)
        if ws is not None:
            ws.result_panel.append_message(f"[执行失败] {err}")
        self._status("执行失败", 8000)

    # ---- 其它动作 ----
    def _format_sql(self) -> None:
        editor = self._active_editor()
        if editor is None:
            return
        cursor = editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText().replace("\u2029", "\n")
            cursor.insertText(format_sql(text))
        else:
            cursor.select(cursor.Document)
            cursor.insertText(format_sql(editor.toPlainText()))
        self._status("SQL 已美化")

    def _insert_history(self) -> None:
        recent = self._history.load()
        if not recent:
            QMessageBox.information(self, "历史 SQL", "暂无历史记录。")
            return
        editor = self._active_editor()
        if editor is None:
            return
        sql, ok = QInputDialog.getItem(self, "最近执行的 SQL", "选择插入：", recent, 0, False)
        if ok and sql:
            editor.insertPlainText(("\n" if editor.toPlainText().strip() else "") + sql)

    def _open_snippets(self) -> None:
        from magiccat.services.snippets import SnippetStore
        from magiccat.ui.snippet_dialog import SnippetDialog

        def insert(sql: str) -> None:
            editor = self._active_editor()
            if editor is not None:
                editor.insertPlainText(("\n" if editor.toPlainText().strip() else "") + sql)

        SnippetDialog(SnippetStore.default(), insert, self).exec()

    def _show_shortcuts(self) -> None:
        QMessageBox.information(self, "快捷键", (
            "<b>执行/编辑</b><br>"
            "F5 — 运行全部 SQL；有选区时运行选中内容<br>"
            "Ctrl+Space — 补全<br>"
            "Ctrl+T — 新建查询标签<br>"
            "Ctrl+W — 关闭当前标签<br><br>"
            "<b>数据页</b><br>"
            "点击表头 — 排序切换<br>"
            "单元格双击 — 编辑（保存按钮提交）<br>"
            "右键 — 复制(TSV)/导出 CSV"))

    def _open_log_dir(self) -> None:
        from magiccat.services.profile_store import ProfileStore

        log_dir = ProfileStore.default().root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            import os

            os.startfile(str(log_dir))
        except OSError as exc:
            QMessageBox.warning(self, "日志目录", f"打开失败：{exc}")

    def _about(self) -> None:
        import magiccat

        QMessageBox.about(
            self, "关于 MagicCat",
            f"<h3>MagicCat {magiccat.__version__}</h3>"
            "<p>对标 Navicat 的跨数据库桌面管理工具（开发版）。</p>"
            "<p>技术栈：PySide6 · JPype(内嵌 JVM) · JDBC(HikariCP + mysql-connector-j)<br>"
            "首发支持：MySQL / MariaDB（Windows）</p>")

    def _add_connection(self) -> None:
        dialog = ConnectionEditDialog(self, groups=self._connections.groups)
        if dialog.exec():
            self._connections.add(dialog.profile())
            self.explorer.load_profiles()
            self._reload_connection_combo()
            self._status("连接已保存", 3000)

    def _test_prompt(self) -> None:
        profiles = self._connections.profiles
        if not profiles:
            QMessageBox.information(self, "测试连接", "请先新增一个连接。")
            return
        names = [p.display_name for p in profiles]
        name, ok = QInputDialog.getItem(self, "测试连接", "选择要测试的连接：", names, 0, False)
        if not ok:
            return
        profile = profiles[names.index(name)]
        self._status(f"正在测试「{profile.name}」…")
        run_async(
            lambda: self._connections.test(profile),
            lambda version: self._status(f"「{profile.name}」连接成功：{version}", 5000),
            lambda err: QMessageBox.warning(self, "测试连接", f"「{profile.name}」失败：\n{err}"))

    def _on_open_table(self, profile_id: str, database: str, schema: str, table: str) -> None:
        profile = self._connections.get(profile_id)
        if profile is None:
            return
        key = f"{schema}.{table}"
        for i in range(self.editor_tabs.count()):
            widget = self.editor_tabs.widget(i)
            if getattr(widget, "tab_key", None) == key:
                self.editor_tabs.setCurrentIndex(i)
                return
        from magiccat.services.data_service import DataService
        from magiccat.ui.data_table import DataTableWidget

        widget = DataTableWidget(profile, database, schema, table,
                                 DataService(self._connections), self._metadata)
        index = self.editor_tabs.addTab(widget, key)
        self.editor_tabs.setCurrentIndex(index)
        self._status(f"已打开表数据：{key}")

    def _on_design_table(self, profile_id: str, schema: str, table: str) -> None:
        profile = self._connections.get(profile_id)
        if profile is None:
            return
        from magiccat.ui.table_designer import TableDesignerDialog

        dialog = TableDesignerDialog(profile, schema, table, self._connections, self)
        dialog.exec()
        self._reload_table_browse(profile, schema)

    def _delete_table(self, profile_id: str, schema: str, table: str) -> None:
        """删除表（对象页动作）：确认后 DROP TABLE，并刷新「表」对象页。"""
        from magiccat.services.query_service import QueryService

        profile = self._connections.get(profile_id)
        if profile is None:
            return
        sql = f"DROP TABLE `{schema}`.`{table}`"
        if QMessageBox.question(
                self, "删除表",
                f"确定删除表 `{schema}`.{table}？\n\n{sql}",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        def done(results: list[dict]) -> None:
            errors = [r for r in results if r.get("kind") == "error"]
            if errors:
                QMessageBox.warning(self, "删除表", errors[0]["message"])
                return
            self._reload_table_browse(profile, schema)
            self._status(f"表已删除：{schema}.{table}", 4000)

        run_async(lambda: QueryService(self._connections).execute(profile, sql),
                  done, lambda err: QMessageBox.critical(self, "删除表", err))

    def _open_view(self, profile_id: str, schema: str, name: str) -> None:
        """打开视图（对象页动作）：取 SHOW CREATE VIEW 定义，开到一个编辑器标签。"""
        from magiccat.services.ddl_service import DdlService

        profile = self._connections.get(profile_id)
        if profile is None:
            return
        ddl = DdlService(self._connections)

        def fetch() -> str:
            return ddl.show_create_view(profile, schema, name)

        def done(sql: str) -> None:
            self._open_object_tab(
                f"view:{profile_id}:{schema}:{name}", f"{name}（视图）", sql)
            self._set_current_profile(profile_id)
            self._status(f"已打开视图「{name}」", 4000)

        run_async(fetch, done,
                  lambda err: QMessageBox.warning(self, "打开视图", f"失败：{err}"))

    def _delete_view(self, profile_id: str, schema: str, name: str) -> None:
        """删除视图（对象页动作）：确认后 DROP VIEW，并刷新「视图」对象页。"""
        from magiccat.services.query_service import QueryService

        profile = self._connections.get(profile_id)
        if profile is None:
            return
        sql = f"DROP VIEW IF EXISTS `{schema}`.`{name}`"
        if QMessageBox.question(
                self, "删除视图",
                f"确定删除视图 `{schema}`.{name}？\n\n{sql}",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        def done(results: list[dict]) -> None:
            errors = [r for r in results if r.get("kind") == "error"]
            if errors:
                QMessageBox.warning(self, "删除视图", errors[0]["message"])
                return
            self._reload_view_browse(profile, schema)
            self._status(f"视图已删除：{schema}.{name}", 4000)

        run_async(lambda: QueryService(self._connections).execute(profile, sql),
                  done, lambda err: QMessageBox.critical(self, "删除视图", err))

    def _on_create_table(self, profile_id: str, schema: str) -> None:
        profile = self._connections.get(profile_id)
        if profile is None:
            return
        import re

        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新建表", f"在 `{schema}` 中新建表：", "new_table")
        name = (name or "").strip()
        if not ok or not name or not re.fullmatch(r"[A-Za-z0-9_]+", name):
            return
        from magiccat.ui.table_designer import TableDesignerDialog

        dialog = TableDesignerDialog(profile, schema, name, self._connections,
                                     self, new_table=True)
        dialog.exec()
        self.explorer.refresh_schema(profile_id, schema)
        self._status(f"新建表完成：{schema}.{name}")

    def _open_import_dialog(self) -> None:
        from magiccat.ui.transfer_dialogs import ImportCsvDialog

        dialog = ImportCsvDialog(self._connections, self._metadata, self)
        dialog.exec()

    def _open_backup_dialog(self) -> None:
        from magiccat.ui.backup_dialogs import BackupDialog

        BackupDialog(self._connections, self._metadata, self).exec()

    def _open_copy_dialog(self) -> None:
        from magiccat.ui.transfer_dialogs import CopyTableDialog

        CopyTableDialog(self._connections, self._metadata, self).exec()

    def _open_restore_dialog(self) -> None:
        from magiccat.ui.backup_dialogs import run_restore_script

        run_restore_script(self, self._connections, self._metadata)

    def _toggle_theme(self, checked: bool) -> None:
        theme = "dark" if checked else "light"
        apply_theme(self, theme)
        self._settings.set("theme", theme)
        self._status(f"主题已切换为：{theme}")

    def _on_er_database(self, profile_id: str, schema: str) -> None:
        profile = self._connections.get(profile_id)
        if profile is None:
            return
        from magiccat.ui.er_view import ErDialog

        ErDialog(profile, schema, self._connections, self).exec()

    def _open_task_dialog(self) -> None:
        from magiccat.ui.task_dialog import TaskDialog

        TaskDialog(self._connections, self._metadata, self._task_store, self).exec()

    def _scan_due_tasks(self) -> None:
        """到期任务在后台执行（任务间隔≥1 分钟，不阻塞 UI）。"""
        from magiccat.services.tasks import _due, _now_iso, run_backup_task

        due_tasks = [t for t in self._task_store.load()
                     if _due(t) and self._task_lock.try_acquire(t.id)]
        for task in due_tasks:
            profile = self._connections.get(task.profile_id)
            if profile is None:
                self._task_lock.release(task.id)
                continue

            def run(t=task, p=profile) -> None:
                try:
                    status = run_backup_task(t, p, self._connections)
                except Exception as exc:  # noqa: BLE001
                    status = f"失败：{exc}"
                finally:
                    self._task_lock.release(t.id)
                t.last_run = _now_iso()
                t.last_status = status
                self._task_store.save([x for x in self._task_store.load()
                                       if x.id != t.id] + [t])
                self._status(f"计划任务「{t.name}」：{status}", 8000)

            run_async(run, lambda _none: None, lambda err: None)

    def _explain_current(self) -> None:
        """对当前 SELECT/SHOW/DESCRIBE 生成 EXPLAIN 执行计划（MySQL 方言路径）。"""
        import re

        ws = self._current_query_ws()
        if ws is None:
            return
        profile = self._current_profile()
        if profile is None:
            QMessageBox.information(self, "EXPLAIN", "请先在工具栏选择要执行的连接。")
            return
        editor = ws.editor
        sql = (editor.current_sql() or "").strip()
        if not sql:
            self._status("无可 EXPLAIN 的语句（选中或光标所在语句）")
            return
        if not re.match(r"(?is)^\s*(explain\b|select\b|with\b|show\b|describe\b)", sql):
            self._status("仅支持对 SELECT/WITH/SHOW/DESCRIBE 生成执行计划", 6000)
            return
        target = sql if re.match(r"(?is)^\s*explain\b", sql) else "EXPLAIN " + sql
        catalog, schema = self._workspace_context(ws, profile)
        self._status(f"正在生成执行计划（{profile.name}）…")
        ws.result_panel.append_message(f"──── EXPLAIN · {profile.name} · {target}")
        run_async(
            lambda: self._query.execute(profile, target, database=catalog, schema=schema),
            lambda results: self._on_explained(results, ws),
            lambda err: self._on_exec_error(err, ws))

    def _on_explained(self, results: list[dict], ws=None) -> None:
        errors = [r for r in results if r.get("kind") == "error"]
        if errors:
            self.result_panel.append_message(f"[EXPLAIN 失败] {errors[0]['message']}")
            self._status("执行计划失败", 8000)
            return
        if ws is not None:
            ws.result_panel.show_results(results)
        rows = sum(len(r.get("rows", [])) for r in results)
        self._status(f"执行计划完成（{rows} 行步骤）", 5000)

    def _save_query_dialog(self) -> None:
        """把当前编辑器另存为“具名查询”（对标 Navicat 查询库）。"""
        from magiccat.services.query_library import QueryLibrary

        profile = self._current_profile()
        if profile is None:
            QMessageBox.information(self, "保存查询", "请先在工具栏选择要保存到的连接。")
            return
        editor = self._active_editor()
        if editor is None or not editor.toPlainText().strip():
            QMessageBox.information(self, "保存查询", "编辑器没有可保存的内容。")
            return
        name, ok = QInputDialog.getText(
            self, "保存查询", f"查询名称：保存位置：{profile.display_name} · "
                              f"{profile.database or '默认'}")
        name = (name or "").strip()
        if not ok or not name:
            return
        ws = self._current_query_ws()
        if ws is not None:
            catalog, current_schema = self._workspace_context(ws, profile)
            # 查询库存储字段仍称 schema：PG 保存实际模式，MySQL 保存 catalog（database）。
            schema = current_schema or catalog
        else:
            schema = self.schema_combo.currentText() or profile.database or ""
        lib = QueryLibrary.default()
        lib.save(profile.id, name, editor.toPlainText(), schema=schema)
        if schema:
            self.explorer.refresh_schema_queries(profile.id, schema)
        self._reload_query_browse()
        self._status(f"查询已保存：{name}（{profile.display_name} · {schema or '默认'}）", 5000)

    def _open_saved_query(self, profile_id: str, name: str) -> None:
        from magiccat.services.query_library import QueryLibrary

        record = QueryLibrary.default().get(profile_id, name)
        profile = self._connections.get(profile_id)
        if record is None or profile is None:
            return
        tab_key = f"query:{profile_id}:{name}"
        ws = self._open_object_tab(tab_key, name, record["content"])
        self._set_current_profile(profile_id)
        # 具名查询的上下文随标签打开：MySQL 保存字段是 Catalog，PG 是 Schema。
        saved_scope = (record.get("schema") or "").strip()
        if profile.is_postgres:
            ws.set_database(profile.database)
            if saved_scope:
                ws.set_schema(saved_scope)
        else:
            ws.set_database(saved_scope or profile.database)
        self._status(f"已打开查询「{name}」（{profile.display_name}"
                     f"{' · ' + record['schema'] if record.get('schema') else ''}）", 5000)

    def _delete_saved_query(self, profile_id: str, name: str) -> None:
        """删除查询：确认后从收藏库移除，并刷新浏览态 + 树。"""
        from magiccat.services.query_library import QueryLibrary

        if not name:
            return
        if QMessageBox.question(self, "删除查询", f"删除查询「{name}」？"
                                ) != QMessageBox.Yes:
            return
        QueryLibrary.default().delete(profile_id, name)
        self._reload_query_browse()
        profile = self._connections.get(profile_id)
        schema = profile.database if profile else ""
        if schema:
            self.explorer.refresh_schema_queries(profile_id, schema)
        self._status(f"查询已删除：{name}", 4000)

    def _on_create_routine(self, profile_id: str, schema: str) -> None:
        """函数向导：选 过程/函数 + 名称 → 编辑器生成模板 SQL。"""
        from magiccat.ui.routine_wizard import RoutineWizardDialog

        profile = self._connections.get(profile_id)
        if profile is None:
            return
        dialog = RoutineWizardDialog(self)
        if not dialog.exec():
            return
        self._open_routine_template(profile, schema, dialog.kind(), dialog.name())

    def _open_routine_template(self, profile, schema: str, kind: str, name: str) -> None:
        def ident(n: str) -> str:
            return "`" + n.replace("`", "``") + "`"

        qname = f"{ident(schema)}.{ident(name)}"
        if kind == "FUNCTION":
            body = (
                "DELIMITER $$\n"
                f"CREATE FUNCTION {qname}() RETURNS INT\n"
                "DETERMINISTIC\n"
                "BEGIN\n"
                "    RETURN 1;\n"
                "END$$\n"
                "DELIMITER ;\n")
        else:
            body = (
                "DELIMITER $$\n"
                f"CREATE PROCEDURE {qname}()\n"
                "BEGIN\n"
                "    -- TODO: 编写过程体\n"
                "    SELECT 1;\n"
                "END$$\n"
                "DELIMITER ;\n")
        editor = self._new_editor()
        editor.setPlainText(body)
        index = self.editor_tabs.indexOf(editor)
        label = name + ("（函数）" if kind == "FUNCTION" else "（过程）")
        self.editor_tabs.setTabText(index, label)
        self._set_current_profile(profile.id)
        verb = "函数" if kind == "FUNCTION" else "过程"
        self._status(
            f"已生成「{verb} {schema}.{name}」模板：填写内容后「运行」即可创建"
            "（体含分号，编辑器支持 DELIMITER 语法）", 8000)

    def _open_routine_sql(self, profile_id: str, name: str, sql_text: str) -> None:
        profile = self._connections.get(profile_id)
        if profile is None:
            return
        self._open_object_tab(f"routine:{profile_id}:{name}",
                              name + "（函数）", sql_text)
        self._set_current_profile(profile_id)
        self._status(
            f"已打开例程「{name}」定义：可查看/修改；改动后需先删除再执行创建"
            "（或用编辑器结合删除动作）, 双击即可再次查看", 8000)

    def _open_routine(self, profile_id: str, name: str, kind: str) -> None:
        """打开函数（对象页动作）：取 SHOW CREATE 定义，开到一个编辑器标签。"""
        from magiccat.services.ddl_service import DdlService

        profile = self._connections.get(profile_id)
        if profile is None:
            return
        schema = self.schema_combo.currentText() or profile.database or ""
        ddl = DdlService(self._connections)

        def fetch() -> str:
            return ddl.show_create_routine(profile, schema, name, kind)

        def done(sql_text: str) -> None:
            self._open_routine_sql(profile_id, name, sql_text)

        run_async(fetch, done,
                  lambda err: QMessageBox.warning(self, "打开函数", f"失败：{err}"))

    def _delete_routine(self, profile_id: str, schema: str, name: str) -> None:
        """删除函数/过程（对象页动作）：确认后 DROP，并刷新「函数」对象页。"""
        profile = self._connections.get(profile_id)
        if profile is None:
            return

        def fetch_type() -> str:
            # 依据 routines 列表判定类型，决定 DROP 词
            for r in self._metadata.routines(profile, schema):
                if r.get("name") == name:
                    return r.get("type", "FUNCTION").upper()
            return "FUNCTION"

        def ask(rtype: str) -> None:
            word = "FUNCTION" if rtype == "FUNCTION" else "PROCEDURE"
            sql = f"DROP {word} IF EXISTS `{schema}`.`{name}`"
            if QMessageBox.question(
                    self, "删除对象",
                    f"确定删除 {word} `{schema}`.{name}？\n\n{sql}",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            from magiccat.services.query_service import QueryService

            def done(results: list[dict]) -> None:
                errors = [r for r in results if r.get("kind") == "error"]
                if errors:
                    QMessageBox.warning(self, "删除对象", errors[0]["message"])
                    return
                self._reload_routine_browse(profile, schema)
                self._status(f"已删除 {word}：{schema}.{name}", 4000)

            run_async(lambda: QueryService(self._connections).execute(profile, sql),
                      done, lambda err: QMessageBox.critical(self, "删除对象", err))

        run_async(fetch_type, ask,
                  lambda err: QMessageBox.warning(self, "删除对象", f"失败：{err}"))

    def _open_trigger(self, profile_id: str, schema: str, name: str) -> None:
        """打开触发器（对象页动作）：取 SHOW CREATE TRIGGER 定义，开到一个编辑器标签。"""
        from magiccat.services.ddl_service import DdlService

        profile = self._connections.get(profile_id)
        if profile is None:
            return
        ddl = DdlService(self._connections)

        def fetch() -> str:
            return ddl.show_create_trigger(profile, schema, name)

        def done(sql_text: str) -> None:
            self._open_object_tab(
                f"trigger:{profile_id}:{schema}:{name}", f"{name}（触发器）", sql_text)
            self._set_current_profile(profile_id)
            self._status(f"已打开触发器「{name}」", 4000)

        run_async(fetch, done,
                  lambda err: QMessageBox.warning(self, "打开触发器", f"失败：{err}"))

    def _delete_trigger(self, profile_id: str, schema: str, name: str) -> None:
        """删除触发器（对象页动作）：确认后 DROP TRIGGER，并刷新「触发器」对象页。"""
        from magiccat.services.query_service import QueryService

        profile = self._connections.get(profile_id)
        if profile is None:
            return
        sql = f"DROP TRIGGER IF EXISTS `{schema}`.`{name}`"
        if QMessageBox.question(
                self, "删除触发器",
                f"确定删除触发器 `{schema}`.{name}？\n\n{sql}",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        def done(results: list[dict]) -> None:
            errors = [r for r in results if r.get("kind") == "error"]
            if errors:
                QMessageBox.warning(self, "删除触发器", errors[0]["message"])
                return
            self._reload_trigger_browse(profile, schema)
            self._status(f"触发器已删除：{schema}.{name}", 4000)

        run_async(lambda: QueryService(self._connections).execute(profile, sql),
                  done, lambda err: QMessageBox.critical(self, "删除触发器", err))

    def _on_selection_info(self, desc: dict) -> None:
        self.info_panel.show_object(desc)

    def _show_object_info(self, desc: dict) -> None:
        """对象页选中某行 → 右侧「信息」面板联动。"""
        self.info_panel.show_object(desc)

    def _on_domain_selected(self, profile_id: str, schema: str, cat_type: str) -> None:
        """对象树选中某分类 → 「对象」页切到该领域子页并按选中库展示列表。"""
        self._set_current_profile(profile_id)
        self._show_domain(cat_type, schema=schema)

    def _on_object_context_selected(self, profile_id: str, database: str,
                                    schema: str, cat_type: str) -> None:
        """左树跟手只更新固定「对象」页，不改写已打开查询工作区。"""
        self._object_context = (profile_id, database, schema)
        if profile_id:
            self._set_current_profile(profile_id)
        self._show_domain(cat_type, schema=schema, database=database, activate=False)

    def _on_new_query_from_explorer(self, profile_id: str, database: str,
                                    schema: str) -> None:
        """对象树「新建查询」（database 级 / schema 级）：新建查询编辑器并定位连接/库。"""
        profile = self._connections.get(profile_id)
        if profile is None:
            return
        self._set_current_profile(profile_id)
        # 右键目标优先级高于全局/当前标签上下文；库级传空 schema，
        # 模式级传具体 schema，均作为一次性初始化值写入新标签。
        self._new_editor_with_context(
            profile_id, database or profile.database or "",
            schema if profile.is_postgres else None,
            schema_explicit=profile.is_postgres)
        self._status("已新建查询"
                     + (f"（{database} · {schema}）" if schema else
                        (f"（{database}）" if database else "")), 4000)

    def _status(self, message: str, timeout: int = 0) -> None:
        self.statusBar().showMessage(message, timeout)
        logger.info(message)
