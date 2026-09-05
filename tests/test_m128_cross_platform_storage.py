"""M128 测试：连接配置使用跨平台用户数据目录和版本化 JSON。"""

from __future__ import annotations

import json

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
        provider_key="mariadb",
    )
    store = JsonProfileStore(tmp_path)

    store.save([profile])

    assert store.path == tmp_path / "connections.json"
    document = json.loads(store.path.read_text(encoding="utf-8"))
    assert document["version"] == 1
    assert document["connections"][0]["id"] == profile.id
    assert document["connections"][0]["password"] == profile.password
    assert profile.password in store.path.read_text(encoding="utf-8")
    assert store.load() == [profile]


def test_json_profile_store_ignores_legacy_profile_file(tmp_path):
    (tmp_path / "profiles.json").write_text(
        json.dumps({"profiles": [{"id": "legacy", "name": "旧配置"}]}),
        encoding="utf-8",
    )

    assert JsonProfileStore(tmp_path).load() == []


def test_home_dir_follows_platform_user_data_conventions(monkeypatch, tmp_path):
    monkeypatch.delenv("MAGICCAT_HOME", raising=False)

    monkeypatch.setattr("magiccat.storage.sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert home_dir() == tmp_path / "roaming" / "MagicCat"

    monkeypatch.setattr("magiccat.storage.sys.platform", "darwin")
    assert home_dir().parts[-3:] == ("Library", "Application Support", "MagicCat")

    monkeypatch.setattr("magiccat.storage.sys.platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert home_dir() == tmp_path / "config" / "MagicCat"
