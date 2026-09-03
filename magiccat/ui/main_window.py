"""主窗口（M3）：连接选择 + 多标签 SQL 编辑器 + 执行流 + 结果面板。

执行模型：所有 JDBC 在后台线程执行（run_async），主线程只负责状态切换与结果展示。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
)

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.history import HistoryStore
from magiccat.services.metadata_service import MetadataService
from magiccat.services.query_service import QueryService
from magiccat.services.sql_text import format_sql
from magiccat.ui.dialogs import ConnectionEditDialog
from magiccat.ui.editor import SqlEditorWidget
from magiccat.ui.job import run_async
from magiccat.ui.object_explorer import ObjectExplorer
from magiccat.ui.result_panel import ResultPanel

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
        self._busy = False
        self._tab_seq = 0

        self.setWindowTitle("MagicCat")
        self.resize(1280, 820)
        self._build_central()
        self._build_explorer_dock()
        self._build_actions()

        self._reload_connection_combo()
        self._new_editor()
        self.statusBar().showMessage("就绪")

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

    def _build_explorer_dock(self) -> None:
        self.explorer = ObjectExplorer(self._connections, self._metadata)
        self.explorer.open_table_requested.connect(self._on_open_table)
        self.explorer.design_table_requested.connect(self._on_design_table)
        dock = QDockWidget("对象浏览器", self)
        dock.setWidget(self.explorer)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.explorer.load_profiles()

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
        menu_query.addSeparator()
        act_format = menu_query.addAction("美化 SQL")
        act_format.triggered.connect(self._format_sql)
        act_history = menu_query.addAction("最近执行的 SQL…")
        act_history.triggered.connect(self._insert_history)
        act_close = menu_query.addAction("关闭当前标签\tCtrl+W")
        act_close.setShortcut("Ctrl+W")
        act_close.triggered.connect(lambda: self._close_editor_tab(self.editor_tabs.currentIndex()))

        menu_tools = self.menuBar().addMenu("工具(&T)")
        act_import = menu_tools.addAction("导入 CSV 到表…")
        act_import.triggered.connect(self._open_import_dialog)

        toolbar = self.addToolBar("查询")
        toolbar.addAction(act_add)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" 连接: "))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        toolbar.addWidget(self.profile_combo)
        toolbar.addSeparator()
        toolbar.addAction(self.act_run)
        toolbar.addAction(self.act_run_all)

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
        self._status(f"当前连接：{profile.name if profile else '未选择'}")
        if profile is not None:
            self._update_completion_words(profile)

    def _update_completion_words(self, profile: ConnectionProfile) -> None:
        def fetch() -> list[str]:
            words: list[str] = []
            for db in self._metadata.databases(profile):
                name = db["name"]
                if name in _SYSTEM_SCHEMAS:
                    continue
                words.extend(t["name"] for t in self._metadata.tables(profile, name))
            return words

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
        if self._busy:
            return
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
        self._busy = True
        self._set_busy(True)
        self._status(f"正在执行（{profile.name}）…")
        self.result_panel.append_message(f"──── 执行 · {profile.name} · {sql}")

        run_async(
            lambda: self._query.execute(profile, sql),
            lambda results: self._on_executed(results),
            lambda err: self._on_exec_error(err))

    def _on_executed(self, results: list[dict]) -> None:
        self._busy = False
        self._set_busy(False)
        self.result_panel.show_results(results)
        errors = [r for r in results if r.get("kind") == "error"]
        total = round(sum(float(r.get("time_ms", 0)) for r in results), 1)
        if errors:
            self._status(f"完成，{len(errors)}/{len(results)} 条语句失败（共 {total} ms）", 8000)
        else:
            self._status(f"完成：{len(results)} 条语句全部成功（共 {total} ms）", 5000)
        editor = self._active_editor()
        if editor is not None:
            self._history.push(editor.all_text())

    def _on_exec_error(self, err: str) -> None:
        self._busy = False
        self._set_busy(False)
        self.result_panel.append_message(f"[执行失败] {err}")
        self._status("执行失败", 8000)

    def _set_busy(self, busy: bool) -> None:
        self.act_run.setEnabled(not busy)
        self.act_run_all.setEnabled(not busy)

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

    def _open_import_dialog(self) -> None:
        from magiccat.ui.transfer_dialogs import ImportCsvDialog

        dialog = ImportCsvDialog(self._connections, self._metadata, self)
        dialog.exec()

    def _status(self, message: str, timeout: int = 0) -> None:
        self.statusBar().showMessage(message, timeout)
        logger.info(message)
