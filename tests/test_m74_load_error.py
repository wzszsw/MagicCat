"""M74 测试：加载失败 → MessageBox 提示 + 树节点折叠（不展示错误占位）。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_load_error_collapses_and_pops_messagebox(qtbot, monkeypatch, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer

    calls = []

    def fake_critical(parent, title, text, *a, **k):
        calls.append((title, text))

    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(fake_critical))

    profile = ConnectionProfile(name="N", group=DEFAULT_GROUP,
                                host="127.0.0.1", port=3306, username="root", password="")
    connection_service.add(profile)

    ex = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(ex)
    ex.load_profiles()

    # 定位 profile 节点
    target = None
    for i in range(ex.topLevelItemCount()):
        it = ex.topLevelItem(i)
        if it.text(0) == "默认分组":
            for j in range(it.childCount()):
                c = it.child(j)
                info = c.data(0, 0x0100) or {}
                if info.get("kind") == "profile" and info.get("data", {}).get("profile_id") == profile.id:
                    target = c
    assert target is not None

    # 直接调用 _show_error（模拟加载失败），断言折叠 + MessageBox
    from magiccat.ui.object_explorer import _replace_children

    _replace_children(target, [])
    target.setExpanded(True)
    ex._show_error(target, "java.lang.java.lang.IllegalStateException: java.lang.IllegalStateException: 连接失败: 用户名或密码错误")
    assert calls, "应弹出 MessageBox 提示"
    title, text = calls[0]
    assert "加载失败" in title
    assert "java.lang" not in text, f"异常文本应清理干净: {text}"
    assert "连接失败: 用户名或密码错误" in text
    assert target.childCount() == 0
    assert not target.isExpanded()
    connection_service.close(profile.id)
