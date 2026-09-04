"""M114 回归：顶部功能域按钮与窗口级当前领域状态保持同步。"""

from __future__ import annotations


def test_domain_toolbar_has_exclusive_selected_state(qtbot, connection_service):
    from PySide6.QtGui import QAction

    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    assert window._current_domain == "tables"
    assert window._domain_actions["tables"].isChecked()
    assert sum(action.isChecked() for action in window._domain_actions.values()) == 1
    assert all(action.isCheckable() for action in window._domain_actions.values())
    assert not window._other_domain_button.isChecked()

    window._show_domain("views")
    assert window._current_domain == "views"
    assert window._domain_actions["views"].isChecked()
    assert not window._domain_actions["tables"].isChecked()
    assert sum(action.isChecked() for action in window._domain_actions.values()) == 1

    window._show_domain("sequences")
    assert window._current_domain == "sequences"
    assert not any(action.isChecked() for action in window._domain_actions.values())
    assert window._other_domain_button.isChecked()

    window._show_domain("tables")
    assert window._current_domain == "tables"
    assert window._domain_actions["tables"].isChecked()
    assert isinstance(window._domain_actions["tables"], QAction)
