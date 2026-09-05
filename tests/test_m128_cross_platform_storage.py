"""M140 测试：连接配置逐文件保存，组索引独立且口令明文。"""

from __future__ import annotations

import json
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.storage import home_dir
from magiccat.storage.profile_store import JsonProfileStore


def test_json_profile_store_roundtrip_and_password_is_plaintext(tmp_path):
    profile = ConnectionProfile(
        name="跨平台配置",
        host="db.example.test",
        port=3307,
        username="admin",
        password="密钥-123!",
        database="app",
        provider_key="MariaDB",
    )
    store = JsonProfileStore(tmp_path)

    store.save_profile(profile)

    path = (tmp_path / "MariaDB" / "Servers" / "跨平台配置"
            / "connection.json")
    assert store.path == tmp_path
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["version"] == 1
    assert document["id"] == profile.id
    assert document["password"] == profile.password
    assert profile.password in path.read_text(encoding="utf-8")
    assert store.load() == [profile]

    store.save_groups([{"name": "常用", "profile_ids": [profile.id]}])
    assert store.load_groups() == [{"name": "常用", "profile_ids": [profile.id]}]


def test_json_profile_store_ignores_legacy_profile_file(tmp_path):
    (tmp_path / "connections.json").write_text(
        json.dumps({"version": 1, "connections": [{"id": "legacy"}]}),
        encoding="utf-8",
    )

    assert JsonProfileStore(tmp_path).load() == []


def test_home_dir_follows_platform_documents_conventions(monkeypatch, tmp_path):
    monkeypatch.delenv("MAGICCAT_HOME", raising=False)

    monkeypatch.setattr("magiccat.storage.sys.platform", "win32")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    assert home_dir() == tmp_path / "profile" / "Documents" / "MagicCat"

    monkeypatch.setattr("magiccat.storage.sys.platform", "darwin")
    assert home_dir() == Path.home() / "Documents" / "MagicCat"

    monkeypatch.setattr("magiccat.storage.sys.platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert home_dir() == Path.home() / "Documents" / "MagicCat"

    config_home = tmp_path / "config"
    config_home.mkdir()
    (config_home / "user-dirs.dirs").write_text(
        'XDG_DOCUMENTS_DIR="$HOME/文档"\n', encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    assert home_dir() == Path.home() / "文档" / "MagicCat"
