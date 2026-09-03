"""M18 测试：对象树名称过滤 + 窗口几何记忆。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_explorer_name_filter(connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer

    connection_service.add(ConnectionProfile(
        name="本地开发库", group=DEFAULT_GROUP, host="127.0.0.1"))
    connection_service.add(ConnectionProfile(
        name="生产服务器", group="生产", host="10.0.0.8"))
    explorer = ObjectExplorer(connection_service, MetadataService(connection_service))
    explorer.load_profiles()

    def texts():
        out = []
        for i in range(explorer.topLevelItemCount()):
            item = explorer.topLevelItem(i)
            if not item.isHidden():
                out.append(item.text(0))
                for c in range(item.childCount()):
                    child = item.child(c)
                    if not child.isHidden():
                        out.append("  " + child.text(0))
        return out

    assert "本地开发库" in "\n".join(texts())

    explorer.apply_name_filter("生产")
    visible = texts()
    assert any("生产" in t for t in visible)
    assert not any("本地" in t for t in visible)
    explorer.apply_name_filter("")
    assert "本地开发库" in "\n".join(texts())  # 清空过滤恢复全显


def test_window_geometry_persisted(qtbot, connection_service):
    import json

    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    win.resize(999, 700)
    win.close()  # 触发 closeEvent → 写入 geometry
    settings_file = connection_service._store.root / "settings.json"
    assert settings_file.exists()
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data.get("geometry"), "应保存窗口几何（base64）"
