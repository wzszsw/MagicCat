"""连接配置文件存储 —— 迁移到 Windows 注册表（对标 Navicat）。

- 连接配置存于 `HKCU\\Software\\MagicCat\\Servers\\<conn_id>`（见 magiccat/storage/registry_store.py）。
- 密码用 Windows DPAPI 加密。
- `root` 属性保留（指向 MAGICCAT_HOME），供日志等位置使用。
- **不兼容旧 profiles.json**：旧文件弃用、不迁移（不留历史包袱）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.storage import home_dir
from magiccat.storage.registry_store import RegistryStore

logger = logging.getLogger(__name__)


class ProfileStore:
    """连接配置存储（注册表实现），接口兼容旧 ProfileStore：load()/save()/root。"""

    def __init__(self, root: Path | None = None, servers_key: str | None = None) -> None:
        self.root = root or home_dir()
        self._reg = RegistryStore(servers_key)

    @classmethod
    def default(cls) -> ProfileStore:
        return cls(home_dir())

    def load(self) -> list[ConnectionProfile]:
        return self._reg.load()

    def save(self, profiles: list[ConnectionProfile]) -> None:
        self._reg.save(profiles)
