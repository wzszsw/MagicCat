"""M26 测试：基于标准 JDBC 的服务器/连接信息 + 右侧面板回填。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_server_info_service(mysql_env, connection_service):
    profile = ConnectionProfile(name="M26", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    info = connection_service.server_info(profile)
    assert "mysql" in info["product"].lower()
    assert info["productVersion"]
    assert info["major"] >= 5
    assert info["url"].startswith("jdbc:mysql://")
    assert info["user"].startswith(mysql_env["user"])
    assert info["driver"].lower().startswith("mysql")
    connection_service.close(profile.id)


def test_connection_info_panel(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.connection_info_panel import ConnectionInfoPanel

    profile = ConnectionProfile(name="M26b", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    panel = ConnectionInfoPanel(connection_service, MetadataService(connection_service))
    qtbot.addWidget(panel)
    panel.show_profile(profile.id)

    def loaded() -> bool:
        return "MySQL" in panel._labels["服务器名称"].text()

    qtbot.waitUntil(loaded, timeout=25_000)
    assert panel._labels["主机"].text() == profile.host
    assert panel._labels["端口"].text() == str(profile.port)
    assert panel._labels["用户名"].text() == profile.username
    assert panel._labels["JDBC URL"].text().startswith("jdbc:mysql://")
    connection_service.close(profile.id)
