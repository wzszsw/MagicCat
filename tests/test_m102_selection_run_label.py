"""M102 回归：选中 SQL 时运行按钮明确提示执行选中内容。"""

from __future__ import annotations


def test_run_button_label_follows_plain_editor_selection(qtbot):
    from PySide6.QtGui import QTextCursor

    from magiccat.ui.editor import SqlEditorWidget
    from magiccat.ui.query_workspace import QueryWorkspace

    workspace = QueryWorkspace(SqlEditorWidget())
    qtbot.addWidget(workspace)
    workspace.setPlainText("SELECT 1;\nSELECT 2;")
    assert workspace.btn_run.text() == "运行"
    assert not hasattr(workspace, "btn_run_all")
    assert workspace.sql_for_run() == "SELECT 1;\nSELECT 2;"

    cursor = workspace.editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(8, QTextCursor.KeepAnchor)
    workspace.editor.setTextCursor(cursor)
    assert workspace.btn_run.text() == "运行已选择的"
    assert workspace.sql_for_run() == "SELECT 1"

    cursor.clearSelection()
    workspace.editor.setTextCursor(cursor)
    assert workspace.btn_run.text() == "运行"
    assert workspace.sql_for_run() == "SELECT 1;\nSELECT 2;"


def test_run_entrypoint_is_single_and_delegates_full_or_selected_sql():
    import inspect

    from magiccat.ui.main_window import MainWindow

    source = inspect.getsource(MainWindow)
    assert "def _run_all" not in source
    assert "act_run_all" not in source
    assert "run_all_requested" not in source
    assert "sql_for_run" in inspect.getsource(MainWindow._run_sql)


def test_monaco_editor_exposes_selection_state_signal():
    import inspect

    from magiccat.ui.monaco_editor import MonacoEditorWidget

    assert hasattr(MonacoEditorWidget, "selectionChanged")
    source = inspect.getsource(MonacoEditorWidget)
    assert "_selection_timer" not in source
    assert "_poll_selection" not in source


def test_monaco_selection_uses_native_event_and_webchannel_bridge():
    from magiccat.ui.monaco_editor import _HTML_SOURCE

    assert "qrc:///qtwebchannel/qwebchannel.js" in _HTML_SOURCE
    assert "new QWebChannel(qt.webChannelTransport" in _HTML_SOURCE
    assert "__editor.onDidChangeCursorSelection" in _HTML_SOURCE
    assert "__bridge.emitSelectionChanged" in _HTML_SOURCE
    assert "getValueInRange(selection)" in _HTML_SOURCE


def test_monaco_bridge_carries_selected_text_snapshot():
    from magiccat.ui.monaco_editor import _Bridge

    bridge = _Bridge()
    captured = []
    bridge.selectionChanged.connect(lambda selected, text: captured.append((selected, text)))

    bridge.emitSelectionChanged(True, "select")

    assert captured == [(True, "select")]
