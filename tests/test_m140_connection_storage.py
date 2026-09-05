"""M140 回归：逐连接配置、独立组索引和树上的未分组呈现。"""

from __future__ import annotations

import json

from magiccat.models.profile import ConnectionProfile


def test_profiles_are_separate_and_groups_are_optional(tmp_path):
    from magiccat.services.connection_service import ConnectionService
    from magiccat.services.profile_store import ProfileStore

    service = ConnectionService(ProfileStore(tmp_path))
    first = ConnectionProfile(name="未分组", password="plain-1")
    second = ConnectionProfile(name="分组内", password="plain-2")
    service.add(first)
    service.add(second)
    service.add_group("工作")
    service.move_to_group(second.id, "工作")

    files = sorted(tmp_path.rglob("connection.json"))
    assert [(path.parent.parent.parent.name, path.parent.name) for path in files] == [
        ("MySQL", "分组内"), ("MySQL", "未分组")
    ]
    assert not (tmp_path / "connections").exists()
    assert json.loads(files[0].read_text(encoding="utf-8"))["password"] in {
        "plain-1", "plain-2"
    }
    assert json.loads((tmp_path / "Premium" / "profiles" / "vgroup.json").read_text(encoding="utf-8")) == {
        "version": "1.1",
        "vgroups": [{
            "vgroup_name": "工作",
            "vgroup_type": "CONNECTION",
            "items": [{
                "name": second.name,
                "type": "CONNECTION",
                "server_type": "MYSQL",
            }],
        }],
        "connections": [],
    }
    assert not (tmp_path / "groups.json").exists()

    reloaded = ConnectionService(ProfileStore(tmp_path))
    assert reloaded.get(first.id).group is None
    assert reloaded.get(second.id).group == "工作"
    reloaded.remove_group("工作")
    assert reloaded.get(second.id).group is None


def test_connection_form_has_no_group_field(qtbot):
    from magiccat.ui.dialogs import ConnectionEditDialog

    dialog = ConnectionEditDialog()
    qtbot.addWidget(dialog)
    assert not hasattr(dialog, "group_combo")


def test_vgroup_file_matches_navicat_shape_and_resolves_by_name_and_product(tmp_path):
    from magiccat.services.connection_service import ConnectionService
    from magiccat.services.profile_store import ProfileStore

    service = ConnectionService(ProfileStore(tmp_path))
    mysql = ConnectionProfile(name="同名", provider_key="MYSQL")
    pg = ConnectionProfile(name="同名", provider_key="PGSQL")
    service.add(mysql)
    service.add(pg)
    service.add_group("数据库")
    service.move_to_group(pg.id, "数据库")

    document = json.loads((tmp_path / "Premium" / "profiles" / "vgroup.json").read_text(encoding="utf-8"))
    assert set(document) == {"version", "vgroups", "connections"}
    assert document["version"] == "1.1"
    assert document["connections"] == []
    assert document["vgroups"][0]["items"] == [{
        "name": "同名",
        "type": "CONNECTION",
        "server_type": "PGSQL",
    }]

    reloaded = ConnectionService(ProfileStore(tmp_path))
    assert reloaded.get(pg.id).group == "数据库"
    assert reloaded.get(mysql.id).group is None


def test_old_groups_json_is_not_read_or_written(tmp_path):
    from magiccat.services.profile_store import ProfileStore

    (tmp_path / "groups.json").write_text(json.dumps({
        "version": 1,
        "groups": [{"name": "旧组", "profile_ids": ["old-id"]}],
    }), encoding="utf-8")
    store = ProfileStore(tmp_path)
    assert store.load_groups() == []
    store.save_groups([])
    assert json.loads((tmp_path / "groups.json").read_text(encoding="utf-8"))["groups"]
    assert json.loads((tmp_path / "Premium" / "profiles" / "vgroup.json").read_text(encoding="utf-8")) == {
        "version": "1.1", "vgroups": [], "connections": []
    }


def test_duplicate_name_is_reported_before_dialog_accepts(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from magiccat.services.connection_service import ConnectionService
    from magiccat.services.profile_store import ProfileStore
    from magiccat.ui.dialogs import ConnectionEditDialog

    service = ConnectionService(ProfileStore(tmp_path))
    existing = ConnectionProfile(name="已存在")
    service.add(existing)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, _title, text, *args: warnings.append(text)),
    )

    dialog = ConnectionEditDialog(name_validator=service.validate_name)
    qtbot.addWidget(dialog)
    dialog._select_product("MYSQL")
    dialog.name_edit.setText("已存在")
    dialog._validate_accept()

    assert dialog.result() == 0
    assert warnings and "同一数据库产品内连接名称必须唯一" in warnings[0]


def test_connection_names_are_unique_per_product_and_renames_follow_filename(tmp_path):
    from magiccat.services.connection_service import ConnectionService
    from magiccat.services.profile_store import ProfileStore

    service = ConnectionService(ProfileStore(tmp_path))
    first = ConnectionProfile(name="同名", password="one")
    service.add(first)

    duplicate = ConnectionProfile(name="同名", password="two")
    try:
        service.add(duplicate)
    except ValueError as exc:
        assert "同一数据库产品内连接名称必须唯一" in str(exc)
    else:
        raise AssertionError("同一数据库产品内不应允许连接名称重复")

    cross_product = ConnectionProfile(name="同名", provider_key="PGSQL")
    service.add(cross_product)
    assert service.get(cross_product.id) is cross_product
    reloaded = ConnectionService(ProfileStore(tmp_path))
    assert {(profile.provider_key, profile.name) for profile in reloaded.profiles} == {
        ("MYSQL", "同名"), ("PGSQL", "同名")
    }

    service.add_group("另一组")
    service.move_to_group(first.id, "另一组")
    renamed = ConnectionProfile(name="新名称", password="one")
    renamed.id = first.id
    service.update(renamed)
    assert (tmp_path / "MySQL" / "Servers" / "新名称"
            / "connection.json").exists()
    assert not (tmp_path / "MySQL" / "Servers" / "同名"
                / "connection.json").exists()
    assert not (tmp_path / "MySQL" / "Servers" / "同名").exists()

    second = ConnectionProfile(name="另一个")
    service.add(second)
    conflicting = ConnectionProfile(name="另一个")
    conflicting.id = first.id
    try:
        service.update(conflicting)
    except ValueError as exc:
        assert "同一数据库产品内连接名称必须唯一" in str(exc)
    else:
        raise AssertionError("重命名到已有连接名时应失败")


def test_storage_does_not_add_collision_suffix(tmp_path):
    from magiccat.services.profile_store import ProfileStore

    store = ProfileStore(tmp_path)
    first = ConnectionProfile(name="a/b")
    store.save_profile(first)
    assert (tmp_path / "MySQL" / "Servers" / "a_b"
            / "connection.json").exists()

    second = ConnectionProfile(name="a:b")
    try:
        store.save_profile(second)
    except ValueError as exc:
        assert "同一文件" in str(exc)
    else:
        raise AssertionError("文件名冲突不应生成数字后缀")
    assert not (tmp_path / "MySQL" / "Servers" / "a_b (2)"
                / "connection.json").exists()


def test_storage_does_not_read_legacy_connection_paths(tmp_path):
    from magiccat.storage.profile_store import JsonProfileStore

    profile = ConnectionProfile(name="旧格式")
    payload = json.dumps({"version": 1, **profile.to_dict(), "password": "plain"})
    paths = (
        tmp_path / "MySQL" / "Servers" / "旧平铺格式.json",
        tmp_path / "connections" / "MySQL" / "Servers" / "旧嵌套格式.json",
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    assert JsonProfileStore(tmp_path).load() == []


def test_service_rejects_duplicate_names_already_on_disk(tmp_path):
    from magiccat.services.connection_service import ConnectionService
    from magiccat.services.profile_store import ProfileStore

    store = ProfileStore(tmp_path)
    store.save_profile(ConnectionProfile(name="重复"))
    # 直接制造无效配置，验证加载时也不放行同一产品内重复名称。
    second = ConnectionProfile(name="重复")
    path = (tmp_path / "MySQL" / "Servers" / "重复-手工"
            / "connection.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, **second.to_dict(), "password": ""}),
        encoding="utf-8",
    )
    try:
        ConnectionService(store)
    except ValueError as exc:
        assert "重复名称" in str(exc)
    else:
        raise AssertionError("磁盘上的重复连接名称也必须拒绝")


def test_saved_queries_follow_product_server_connection_directory(tmp_path):
    from magiccat.services.query_library import QueryLibrary
    from magiccat.storage.profile_store import JsonProfileStore

    profile = ConnectionProfile(name="localhost_1433", provider_key="MSSQL",
                                id="sql-server-profile")
    JsonProfileStore(tmp_path).save_profile(profile)

    library = QueryLibrary(tmp_path)
    library.save(profile.id, "查询一", "SELECT 1", database="app", schema="dbo")

    path = (tmp_path / "SQL Server" / "Servers"
            / "localhost_1433" / "app" / "dbo" / "查询一.sql")
    assert path.read_text(encoding="utf-8") == "SELECT 1"
    assert library.get(profile.id, "查询一")["database"] == "app"
    assert library.get(profile.id, "查询一")["schema"] == "dbo"
    assert not (tmp_path / "queries").exists()


def test_mysql_saved_query_omits_schema_directory(tmp_path):
    from magiccat.services.query_library import QueryLibrary
    from magiccat.storage.profile_store import JsonProfileStore

    profile = ConnectionProfile(name="localhost_3306", provider_key="MYSQL",
                                id="mysql-profile")
    JsonProfileStore(tmp_path).save_profile(profile)
    QueryLibrary(tmp_path).save(profile.id, "查询一", "SELECT 1", database="app")

    assert (tmp_path / "MySQL" / "Servers" / "localhost_3306"
            / "app" / "查询一.sql").exists()


def test_storage_does_not_default_missing_provider_key(tmp_path):
    from magiccat.storage.profile_store import JsonProfileStore

    path = tmp_path / "MySQL" / "Servers" / "invalid" / "connection.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "id": "invalid", "name": "invalid"}),
                    encoding="utf-8")

    assert JsonProfileStore(tmp_path).load() == []


def test_left_tree_dock_title_is_my_connections(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)
    assert window.explorer_dock.windowTitle() == "我的连接"
