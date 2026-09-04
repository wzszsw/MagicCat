"""连接配置的注册表存储（对标 Navicat：连接配置存于注册表）。

- 每个连接一个子键：`HKCU\\Software\\MagicCat\\Servers\\<conn_id>`。
- 字段以 REG_SZ 值存；password 用 Windows DPAPI 加密（见 utils/dpapi.py）。
- 组（group）用注册表值 `group` 区分；`group` 值即分组名。
- 不兼容旧 profiles.json：旧文件弃用、不迁移（不留历史包袱）。
"""

from __future__ import annotations

import logging
import winreg

from magiccat.models.profile import ConnectionProfile
from magiccat.storage import registry_servers_key
from magiccat.utils import dpapi

logger = logging.getLogger(__name__)

# 持久化字段（除 password 外均为存储值，见 ConnectionProfile.to_dict）
_FIELDS = ("id", "name", "group", "host", "port", "username", "database",
           "provider_key", "created_at", "updated_at")


class RegistryStore:
    """连接配置注册表读写。"""

    def __init__(self, servers_key: str | None = None) -> None:
        self.servers_key = servers_key or registry_servers_key()

    @classmethod
    def default(cls) -> RegistryStore:
        return cls()

    # ---- 读 ----
    def load(self) -> list[ConnectionProfile]:
        profiles: list[ConnectionProfile] = []
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.servers_key) as root:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    prof = self._read_one(sub)
                    if prof is not None:
                        profiles.append(prof)
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("注册表读取连接配置失败: %s", exc)
        return profiles

    def _read_one(self, conn_id: str) -> ConnectionProfile | None:
        key = self.servers_key + "\\" + conn_id
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as sub:
                data = {f: self._get_value(sub, f) for f in _FIELDS}
                port = int(data.get("port") or 0)
                enc = self._get_value(sub, "password_enc")
            if not data.get("name"):
                return None
            return ConnectionProfile(
                name=data.get("name", ""),
                host=data.get("host", "127.0.0.1"),
                port=port,
                username=data.get("username", "root"),
                password=dpapi.decrypt_text(enc or ""),
                database=data.get("database", ""),
                group=data.get("group", "默认分组"),
                provider_key=data.get("provider_key", "mysql"),
                id=conn_id,
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            )
        except OSError as exc:
            logger.warning("读取连接 %s 失败: %s", conn_id, exc)
            return None

    @staticmethod
    def _get_value(sub, name: str) -> str:
        try:
            val, _t = winreg.QueryValueEx(sub, name)
            return str(val) if val is not None else ""
        except OSError:
            return ""

    # ---- 写 ----
    def save(self, profiles: list[ConnectionProfile]) -> None:
        """全量落库：以 profiles 为准重建所有连接子键。"""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.servers_key,
                                0, winreg.KEY_ALL_ACCESS) as root:
                # 先清空现有子键，再写入，保证与传入列表一致
                existing = []
                i = 0
                while True:
                    try:
                        existing.append(winreg.EnumKey(root, i))
                    except OSError:
                        break
                    i += 1
                for sub in existing:
                    winreg.DeleteKey(root, sub)
                for p in profiles:
                    self._write_one(p)
        except FileNotFoundError:
            # 父键不存在：创建
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.servers_key) as root:
                    for p in profiles:
                        self._write_one(p)
            except OSError as exc:
                logger.warning("创建注册表存储失败: %s", exc)
        except OSError as exc:
            logger.warning("保存注册表连接配置失败: %s", exc)

    def _write_one(self, p: ConnectionProfile) -> None:
        key = self.servers_key + "\\" + p.id
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as sub:
            d = p.to_dict()
            for f in _FIELDS:
                winreg.SetValueEx(sub, f, 0, winreg.REG_SZ, str(d.get(f, "")))
            winreg.SetValueEx(sub, "password_enc", 0, winreg.REG_SZ,
                              dpapi.encrypt_text(p.password))
