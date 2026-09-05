"""连接配置服务门面。

具体持久化由跨平台 JSON 存储实现；``root`` 属性供日志等应用数据使用。
"""

from __future__ import annotations

from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.storage import home_dir
from magiccat.storage.profile_store import JsonProfileStore


class ProfileStore:
    """连接配置存储（跨平台 JSON 实现）。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else home_dir()
        self._json = JsonProfileStore(self.root)

    @classmethod
    def default(cls) -> ProfileStore:
        return cls(home_dir())

    def load(self) -> list[ConnectionProfile]:
        return self._json.load()

    def save(self, profiles: list[ConnectionProfile]) -> None:
        self._json.save(profiles)

    @property
    def config_path(self) -> Path:
        """当前连接配置文件路径，供信息面板等只读展示。"""
        return self._json.path
