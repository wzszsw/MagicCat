"""主窗口（M3）：连接选择 + 多标签 SQL 编辑器 + 执行流 + 结果面板。

执行模型：所有 JDBC 在后台线程执行（run_async），主线程只负责状态切换与结果展示。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
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
from magiccat.ui.dialogs import ConnectionEditDialog
from magiccat.ui.editor import SqlEditorWidget
from magiccat.ui.job import run_async
from magiccat.ui.object_explorer import ObjectExplorer
from magiccat.ui.result_panel import ResultPanel
from magiccat.ui.theme import apply_theme

logger = logging.getLogger(__name__)

_SYSTEM_SCHEMAS = {"information_schema", "performance_schema", "mysql", "sys"}


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
        self._new_editor()
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
        splitter = QSplitter(Qt.Vertical)
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setTabsClosable(True)
        self.editor_tabs.tabCloseRequested.connect(self._close_editor_tab)
        self.result_panel = ResultPanel()
        splitter.addWidget(self.editor_tabs)
        splitter.addWidget(self.result_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        # Navicat：消息窗默认不显示，有消息/结果时自动出现
        self.result_panel.setVisible(False)

    def _build_explorer_dock(self) -> None:
        self.explorer = ObjectExplorer(self._connections, self._metadata)
        self.explorer.open_table_requested.connect(self._on_open_table)
        self.explorer.design_table_requested.connect(self._on_design_table)
        self.explorer.er_database_requested.connect(self._on_er_database)
        self.explorer.create_table_requested.connect(self._on_create_table)
        self.explorer.open_saved_query.connect(self._open_saved_query)
        self.explorer.create_routine_entry.connect(self._on_create_routine)
        self.explorer.open_routine_sql.connect(self._open_routine_sql)
        dock = QDockWidget("对象浏览器", self)

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
        self.explorer.load_profiles()

    def _build_info_dock(self) -> None:
        from magiccat.ui.connection_info_panel import ConnectionInfoPanel

        self.info_panel = ConnectionInfoPanel(self._connections, self._metadata)
        dock = QDockWidget("连接信息", self)
        dock.setWidget(self.info_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_quick_toolbar(self) -> None:
        """对标 Navicat 顶部快速访问栏（图标+文字在下）；仅放已实现功能，
        未实现的（其它/BI）不放置。"""
        from magiccat.ui.icons import icon

        toolbar = QToolBar("快速访问")
        toolbar.setObjectName("quick_toolbar")
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.addToolBar(toolbar)

        def quick(text: str, kind: str, handler) -> None:
            act = QAction(icon(kind), text, self)
            act.setToolTip(text)
            act.triggered.connect(handler)
            toolbar.addAction(act)

        quick("连接", "connection", self._add_connection)
        quick("新建查询", "new_query", self._new_editor)
        toolbar.addSeparator()
        quick("表", "table", lambda: self._quick_create_object("table"))
        quick("视图", "view", lambda: self._quick_create_object("view"))
        quick("函数", "function", lambda: self._quick_create_object("routine"))
        toolbar.addSeparator()
        quick("用户", "user", self._quick_user)
        toolbar.addSeparator()
        quick("查询", "query", self._new_editor)
        quick("备份", "backup", self._open_backup_dialog)
        quick("自动运行", "auto_run", self._open_task_dialog)
        quick("模型", "model", self._quick_model)

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

    def _quick_model(self) -> None:
        """模型：当前库的 ER 图。"""
        schema = self._resolve_current_schema()
        if not schema:
            return
        profile = self._current_profile()
        from magiccat.ui.er_view import ErDialog

        ErDialog(profile, schema, self._connections, self).exec()

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
                self._status("新建视图模板已生成：填写 SELECT 后「执行全部」创建", 8000)
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
        self.act_run = menu_query.addAction("执行(当前/选中)\tF5")
        self.act_run.setShortcut("F5")
        self.act_run.triggered.connect(self._run_current)
        self.act_run_all = menu_query.addAction("执行全部\tCtrl+Shift+Enter")
        self.act_run_all.setShortcut("Ctrl+Shift+Enter")
        self.act_run_all.triggered.connect(self._run_all)
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
        act_tasks = menu_tools.addAction("计划任务…")
        act_tasks.triggered.connect(self._open_task_dialog)
        act_copy = menu_tools.addAction("复制表（数据传输）…")
        act_copy.triggered.connect(self._open_copy_dialog)
        act_restore = menu_tools.addAction("执行 SQL 脚本（恢复）…")
        act_restore.triggered.connect(self._open_restore_dialog)

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

        # 查询工具栏（对标 Navicat：查询编辑区上方 连接/库 + 保存/美化/运行/停止/解释）
        qtb = QToolBar("查询工具")
        qtb.setObjectName("query_toolbar")
        self.addToolBar(qtb)
        qtb.addWidget(QLabel(" 连接: "))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        qtb.addWidget(self.profile_combo)
        qtb.addWidget(QLabel(" 库: "))
        self.schema_combo = QComboBox()
        self.schema_combo.setMinimumWidth(160)
        self.schema_combo.currentIndexChanged.connect(
            lambda _: None)  # 主要用于选择执行目标库（存入 _current_schema 供保存位置）
        qtb.addWidget(self.schema_combo)
        qtb.addSeparator()
        qtb.addAction(self.act_save_query)
        qtb.addAction(self.act_format)
        qtb.addAction(self.act_run)
        qtb.addAction(self.act_run_all)
        qtb.addAction(self.act_cancel)
        qtb.addAction(self.act_explain)

    # ---- 连接选择 ----
    def _reload_connection_combo(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("<未选择连接>", None)
        for p in self._connections.profiles:
            self.profile_combo.addItem(p.display_name, p.id)
        self.profile_combo.blockSignals(False)

    def _current_profile(self) -> ConnectionProfile | None:
        pid = self.profile_combo.currentData()
        if not pid:
            return None
        return self._connections.get(pid)

    def _on_profile_selected(self) -> None:
        profile = self._current_profile()
        self.setWindowTitle(f"MagicCat — {profile.display_name}" if profile else "MagicCat")
        self._status(f"当前连接：{profile.name if profile else '未选择'}")
        self.info_panel.show_profile(self.profile_combo.currentData() if profile else None)
        self._reload_schema_combo(profile)

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

        run_async(fetch, done, lambda err: logger.warning("加载库下拉失败: %s", err))
        if profile is not None:
            self._update_completion_words(profile)

    def _update_completion_words(self, profile: ConnectionProfile) -> None:
        def fetch() -> list[str]:
            from magiccat.services.query_service import QueryService

            # 一次批查所有用户库的表名（消除“每库一次查询”的 N+1）
            excluded = "', '".join(sorted(_SYSTEM_SCHEMAS))
            res = QueryService(self._connections).execute(profile, (
                "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
                f"WHERE TABLE_TYPE = 'BASE TABLE' "
                f"AND TABLE_SCHEMA NOT IN ('{excluded}')"))[0]
            cols = res.get("columns", [])
            return [row[cols.index("name")] for row in res.get("rows", []) if cols]

        def done(words: list[str]) -> None:
            editor = self._active_editor()
            if editor is not None:
                editor.set_completion_words(words)
            self._status(f"补全词表已更新（{len(words)} 个对象）")

        run_async(fetch, done, lambda err: logger.warning("加载补全词表失败: %s", err))

    # ---- 编辑器管理 ----
    def _new_editor(self) -> SqlEditorWidget:
        self._tab_seq += 1
        editor = SqlEditorWidget()
        editor.setPlaceholderText(
            "输入 SQL（Ctrl+Space 补全，F5 执行当前语句/选中，Ctrl+Shift+Enter 执行全部）")
        index = self.editor_tabs.addTab(editor, f"查询 {self._tab_seq}")
        self.editor_tabs.setCurrentIndex(index)
        editor.setFocus()
        return editor

    def _active_editor(self) -> SqlEditorWidget | None:
        widget = self.editor_tabs.currentWidget()
        return widget if isinstance(widget, SqlEditorWidget) else None

    def _close_editor_tab(self, index: int) -> None:
        if self.editor_tabs.count() <= 1:
            return
        self.editor_tabs.removeTab(index)

    # ---- 执行流 ----
    def _run_current(self) -> None:
        self._run_sql(all_statements=False)

    def _run_all(self) -> None:
        self._run_sql(all_statements=True)

    def _run_sql(self, all_statements: bool) -> None:
        profile = self._current_profile()
        if profile is None:
            QMessageBox.information(self, "执行 SQL", "请先在工具栏选择要执行的连接。")
            return
        editor = self._active_editor()
        if editor is None:
            return
        sql = editor.all_text() if all_statements else (editor.current_sql() or "")
        if not sql.strip():
            self._status("无可执行内容：请选中文本或把光标放在语句上")
            return
        self._status(f"正在执行（{profile.name}）…")
        self.result_panel.append_message(f"──── 执行 · {profile.name} · {sql}")
        # 支持多标签并行：每次执行独立入池，结果完成时刷新下方结果区
        self._running += 1
        self.act_cancel.setEnabled(True)
        run_async(
            lambda: self._query.execute(profile, sql),
            lambda results: self._on_executed(results),
            lambda err: self._on_exec_error(err))

    def _cancel_execution(self) -> None:
        count = self._query.cancel_all()
        self._status(f"正在取消 {count} 个执行中的查询…")
        if count == 0:
            self.act_cancel.setEnabled(False)

    def _on_executed(self, results: list[dict]) -> None:
        self._running = max(0, self._running - 1)
        self.act_cancel.setEnabled(self._running > 0)
        self.result_panel.show_results(results)
        cancelled = any(r.get("cancelled") for r in results)
        errors = [r for r in results if r.get("kind") == "error"]
        total = round(sum(float(r.get("time_ms", 0)) for r in results), 1)
        if cancelled:
            self._status(f"执行已取消（{total} ms）", 5000)
        elif errors:
            self._status(f"完成，{len(errors)}/{len(results)} 条语句失败（共 {total} ms）", 8000)
        else:
            self._status(f"完成：{len(results)} 条语句全部成功（共 {total} ms）", 5000)
        editor = self._active_editor()
        if editor is not None:
            self._history.push(editor.all_text())

    def _on_exec_error(self, err: str) -> None:
        self._running = max(0, self._running - 1)
        self.act_cancel.setEnabled(self._running > 0)
        self.result_panel.append_message(f"[执行失败] {err}")
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
            "F5 / Ctrl+Enter — 执行当前语句或选中<br>"
            "Ctrl+Shift+Enter — 执行全部<br>"
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

    def _on_open_table(self, profile_id: str, schema: str, table: str) -> None:
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

        widget = DataTableWidget(profile, schema, table,
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

        profile = self._current_profile()
        if profile is None:
            QMessageBox.information(self, "EXPLAIN", "请先在工具栏选择要执行的连接。")
            return
        editor = self._active_editor()
        if editor is None:
            return
        sql = (editor.current_sql() or "").strip()
        if not sql:
            self._status("无可 EXPLAIN 的语句（选中或光标所在语句）")
            return
        if not re.match(r"(?is)^\s*(explain\b|select\b|with\b|show\b|describe\b)", sql):
            self._status("仅支持对 SELECT/WITH/SHOW/DESCRIBE 生成执行计划", 6000)
            return
        target = sql if re.match(r"(?is)^\s*explain\b", sql) else "EXPLAIN " + sql
        self._status(f"正在生成执行计划（{profile.name}）…")
        self.result_panel.append_message(f"──── EXPLAIN · {profile.name} · {target}")
        run_async(
            lambda: self._query.execute(profile, target),
            lambda results: self._on_explained(results),
            lambda err: self._on_exec_error(err))

    def _on_explained(self, results: list[dict]) -> None:
        errors = [r for r in results if r.get("kind") == "error"]
        if errors:
            self.result_panel.append_message(f"[EXPLAIN 失败] {errors[0]['message']}")
            self._status("执行计划失败", 8000)
            return
        self.result_panel.show_results(results)
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
        schema = self.schema_combo.currentText() or profile.database or ""
        lib = QueryLibrary.default()
        lib.save(profile.id, name, editor.toPlainText(), schema=schema)
        if schema:
            self.explorer.refresh_schema_queries(profile.id, schema)
        self._status(f"查询已保存：{name}（{profile.display_name} · {schema or '默认'}）", 5000)

    def _open_saved_query(self, profile_id: str, name: str) -> None:
        from magiccat.services.query_library import QueryLibrary

        record = QueryLibrary.default().get(profile_id, name)
        profile = self._connections.get(profile_id)
        if record is None or profile is None:
            return
        editor = self._new_editor()
        editor.setPlainText(record["content"])
        self.editor_tabs.setTabText(self.editor_tabs.indexOf(editor), name)
        idx = self.profile_combo.findData(profile_id)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        self._status(f"已打开查询「{name}」（{profile.display_name}"
                     f"{' · ' + record['schema'] if record.get('schema') else ''}）", 5000)

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
        idx = self.profile_combo.findData(profile.id)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        verb = "函数" if kind == "FUNCTION" else "过程"
        self._status(
            f"已生成「{verb} {schema}.{name}」模板：填写内容后「执行全部」即可创建"
            "（体含分号，编辑器支持 DELIMITER 语法）", 8000)

    def _open_routine_sql(self, profile_id: str, name: str, sql_text: str) -> None:
        profile = self._connections.get(profile_id)
        if profile is None:
            return
        editor = self._new_editor()
        editor.setPlainText(sql_text)
        index = self.editor_tabs.indexOf(editor)
        self.editor_tabs.setTabText(index, name + "（函数）")
        idx = self.profile_combo.findData(profile_id)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        self._status(
            f"已打开例程「{name}」定义：可查看/修改；改动后需先删除再执行创建"
            "（或用编辑器结合删除动作）, 双击即可再次查看", 8000)

    def _status(self, message: str, timeout: int = 0) -> None:
        self.statusBar().showMessage(message, timeout)
        logger.info(message)
