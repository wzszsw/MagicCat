"""M2 集成测试：配置存取 + 连接生命周期 + 元数据 + 对象树（Qt offscreen）。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def _profile(mysql_env: dict, name: str = "本地测试") -> ConnectionProfile:
    return ConnectionProfile(
        name=name,
        group=DEFAULT_GROUP,
        host=mysql_env["host"],
        port=mysql_env["port"],
        username=mysql_env["user"],
        password=mysql_env["password"],
    )


def test_profile_persistence_password_plaintext(tmp_path, profile_store, connection_service):
    """口令按配置直接存入跨平台 JSON。"""
    import json

    profile = _profile({"host": "h", "port": 1, "user": "u", "password": ""}, "配置测试")
    profile.password = "s3cret中文!@#pass"
    connection_service.add(profile)

    config_path = (profile_store.connections_dir / "MySQL" / "Servers"
                   / "配置测试" / "connection.json")
    document = json.loads(config_path.read_text(encoding="utf-8"))
    assert document["id"] == profile.id
    assert document["password"] == profile.password
    assert profile.password in config_path.read_text(encoding="utf-8")

    from magiccat.services.connection_service import ConnectionService

    reloaded = ConnectionService(profile_store).get(profile.id)
    assert reloaded is not None
    assert reloaded.password == profile.password, "口令回环失败"


def test_open_databases_and_columns(mysql_env, connection_service):
    """真实 MySQL：open → 数据库列表 → 表 → 列 → 索引。"""
    profile = _profile(mysql_env)
    connection_service.add(profile)

    version = connection_service.open(profile)
    assert version

    from magiccat.services.metadata_service import MetadataService

    meta = MetadataService(connection_service)
    dbs = [d["name"] for d in meta.databases(profile)]
    assert "mysql" in dbs and "information_schema" in dbs

    tables = meta.tables(profile, "mysql")
    assert tables
    base_table = next(t for t in tables if t["type"] == "BASE TABLE")
    cols = meta.columns(profile, "mysql", base_table["name"])
    assert cols and cols[0]["name"] and cols[0]["data_type"]
    assert meta.indexes(profile, "mysql", base_table["name"]) is not None


def test_open_failure_raises(mysql_env, connection_service):
    """错误口令打开应抛异常（JPype 上抛 Java 异常）。"""
    profile = _profile(mysql_env, "错误口令")
    profile.password = "definitely-wrong-password"
    connection_service.add(profile)
    import pytest

    with pytest.raises(Exception):  # noqa: B017 —— JPype 上抛的 Java 异常类是动态生成的
        connection_service.open(profile)


def test_object_explorer_loads_databases(qtbot, mysql_env, connection_service):
    """对象树（Qt offscreen）：展开连接后应异步加载出数据库节点，UI 不阻塞。"""
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer

    profile = _profile(mysql_env)
    connection_service.add(profile)
    meta = MetadataService(connection_service)

    explorer = ObjectExplorer(connection_service, meta)
    qtbot.addWidget(explorer)
    explorer.load_profiles()

    item = explorer.profile_item(profile.id)
    assert item is not None, "连接节点应出现在树中"
    item.setExpanded(True)

    def loaded() -> bool:
        if item.childCount() == 0:
            return False
        return all(
            (item.child(i).data(0, 0x0100) or {}).get("kind") != "placeholder"
            for i in range(item.childCount())
        )

    qtbot.waitUntil(loaded, timeout=25_000)
    texts = [item.child(i).text(0) for i in range(item.childCount())]
    assert "mysql" in texts, f"数据库节点缺失，实际: {texts}"
    connection_service.close(profile.id)
