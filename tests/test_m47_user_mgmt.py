"""M47 测试：用户管理（列表/新建/改密/删除/权限/面板）。"""

from __future__ import annotations

import logging
import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services import user_service

logger = logging.getLogger(__name__)


def test_user_service_crud(mysql_env, connection_service):
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M47", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    name = f"mc_m47_u_{int(time.time() * 1000)}"
    try:
        users = user_service.list_users(q, profile)
        assert any(u["user"] == "root" and u["host"] == "localhost" for u in users)

        user_service.create_user(q, profile, name, "localhost", "p@ss1",
                                 plugin="caching_sha2_password", expire="INTERVAL 30 DAY")
        found = next(u for u in user_service.list_users(q, profile)
                     if u["user"] == name and u["host"] == "localhost")
        assert found["plugin"] == "caching_sha2_password"

        user_service.alter_user(q, profile, name, "localhost", password="p@ss2",
                                plugin="caching_sha2_password", expire="NEVER")
        grants = user_service.show_grants(q, profile, name, "localhost")
        assert grants  # SHOW GRANTS 应有内容
        show = q.execute(profile, f"SHOW CREATE USER '{name}'@'localhost'")[0]
        show_text = " ".join(str(v) for v in show["rows"][0])
        assert "PASSWORD EXPIRE NEVER" in show_text, show_text
    finally:
        try:
            user_service.drop_user(q, profile, name, "localhost")
        except Exception as exc:  # noqa: BLE001 —— 可能未创建成功
            logger.warning("清理测试用户失败: %s", exc)
        connection_service.close(profile.id)


def test_user_manager_widget(qtbot, mysql_env, connection_service):
    from PySide6.QtCore import Qt

    from magiccat.ui.user_manager import UserManagerWidget

    profile = ConnectionProfile(name="M47b", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    widget = UserManagerWidget(profile, connection_service)
    qtbot.addWidget(widget)

    def loaded() -> bool:
        model = widget.table.model()
        return model is not None and model.rowCount() >= 1

    qtbot.waitUntil(loaded, timeout=25_000)
    headers = [widget.table.model().headerData(c, Qt.Horizontal)
               for c in range(widget.table.model().columnCount())]
    assert "名称" in headers and "超级用户" in headers
    sample = [widget.table.model().data(widget.table.model().index(r, 0))
              for r in range(widget.table.model().rowCount())]
    assert any("root@localhost" in (s or "") for s in sample), sample
    connection_service.close(profile.id)
