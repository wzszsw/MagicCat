"""M135 回归：用户作为对象页领域，并由窗口状态管理当前领域。"""

from __future__ import annotations


def test_user_toolbar_uses_object_page_and_updates_domain_state(
    qtbot, connection_service
):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)
    initial_tabs = window.editor_tabs.count()

    window._domain_actions["users"].trigger()

    assert window.editor_tabs.count() == initial_tabs
    assert window.editor_tabs.currentIndex() == 0
    assert window.domain_stack.currentWidget() is window.user_page
    assert window._current_domain == "users"
    assert window.state_store.state.current_domain == "users"
    assert window._domain_actions["users"].isChecked()
    assert not window._domain_actions["tables"].isChecked()


def test_user_manager_without_profile_stays_disabled(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    window._show_domain("users")

    assert window.user_page.profile is None
    assert window.user_page.status.text() == "请先选择连接"
    buttons = [window.user_page.btn_new, window.user_page.btn_open,
               window.user_page.btn_del, window.user_page.btn_refresh,
               *window.user_page._tool_buttons]
    assert all(not button.isEnabled() for button in buttons)


def test_user_list_model_provides_user_icon(qtbot, connection_service):
    from magiccat.ui.user_manager import UserManagerWidget

    widget = UserManagerWidget(None, connection_service)
    qtbot.addWidget(widget)
    widget.load("p1", [{"name": "root@localhost"}])
    item = widget.table.item(0, 0)
    assert item is not None
    assert not item.icon().isNull()
