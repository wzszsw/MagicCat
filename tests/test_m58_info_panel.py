"""M58 测试：对象树“选中什么信息面板显示什么”（Navicat 行为）。"""

from __future__ import annotations


def test_explorer_selection_emits_desc(qtbot, connection_service):
    from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer

    profile = ConnectionProfile(name="M58", group=DEFAULT_GROUP, host="127.0.0.1")
    connection_service.add(profile)
    explorer = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(explorer)
    captured: list[dict] = []
    explorer.selection_info_requested.connect(captured.append)
    explorer.load_profiles()
    item = explorer.profile_item(profile.id)
    explorer.setCurrentItem(item)
    assert captured and captured[-1]["kind"] == "profile"
    assert captured[-1]["profile_id"] == profile.id


def test_panel_shows_database_info(qtbot, mysql_env, connection_service):
    from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.connection_info_panel import ConnectionInfoPanel

    profile = ConnectionProfile(name="M58b", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    panel = ConnectionInfoPanel(connection_service, MetadataService(connection_service))
    qtbot.addWidget(panel)
    panel.show_object({"kind": "database", "profile_id": profile.id, "schema": "test"})
    assert panel.title.text().startswith("数据库 · test")

    def loaded() -> bool:
        return "默认字符集" in panel._labels["备注"].text()

    qtbot.waitUntil(loaded, timeout=25_000)
    assert "utf8mb4" in panel._labels["备注"].text()
