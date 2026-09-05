"""M127 回归：定位关闭态连接不切换当前连接或对象工作区。"""

from __future__ import annotations


def test_closed_profile_selection_only_updates_info(qtbot, connection_service, monkeypatch):
    from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer

    profile = ConnectionProfile(name="关闭态", group=DEFAULT_GROUP,
                                host="127.0.0.1", port=3306)
    connection_service.add(profile)
    explorer = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(explorer)

    info: list[dict] = []
    activated: list[str] = []
    contexts: list[tuple[str, str, str, str]] = []
    domains: list[tuple[str, str, str]] = []
    explorer.selection_info_requested.connect(info.append)
    explorer.profile_activated.connect(activated.append)
    explorer.object_context_selected.connect(
        lambda pid, database, schema, cat: contexts.append((pid, database, schema, cat)))
    explorer.domain_selected.connect(
        lambda pid, schema, cat: domains.append((pid, schema, cat)))

    explorer.load_profiles()
    item = explorer.profile_item(profile.id)
    assert item is not None
    explorer.setCurrentItem(item)

    assert info and info[-1] == {"kind": "profile", "profile_id": profile.id}
    assert activated == []
    assert contexts == []
    assert domains == []

    # 打开态仍保留原有的跟手行为。
    explorer.setCurrentItem(None)
    info.clear()
    monkeypatch.setattr(connection_service, "is_open", lambda pid: pid == profile.id)
    explorer.setCurrentItem(item)
    assert activated == [profile.id]
    assert contexts == [(profile.id, "", "", "tables")]
