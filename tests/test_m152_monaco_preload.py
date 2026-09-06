"""M152 回归：Monaco 只在窗口显示后局部预热，不占用查询标签。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


def test_preloaded_monaco_workspace_is_not_a_tab_and_is_reused(
    qtbot, connection_service, monkeypatch
) -> None:
    from magiccat.ui import main_window as main_window_module
    from magiccat.ui.main_window import MainWindow

    class FakeMonacoEditor(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.load_calls = 0

        def load(self) -> None:
            self.load_calls += 1

        def has_selection(self) -> bool:
            return False

        def setFocus(self) -> None:
            pass

    monkeypatch.setattr(main_window_module, "MonacoEditorWidget", FakeMonacoEditor)
    monkeypatch.delenv("MAGICCAT_EDITOR", raising=False)
    window = MainWindow(connection_service)
    qtbot.addWidget(window)

    assert window.editor_tabs.count() == 1
    window._preload_monaco_workspace()
    preloaded = window._preloaded_query_workspace
    assert preloaded is not None
    assert preloaded.editor.load_calls == 1
    assert window.editor_tabs.count() == 1

    workspace = window._new_editor()
    assert workspace is preloaded
    assert window.editor_tabs.currentWidget() is preloaded
    assert window.editor_tabs.count() == 2
