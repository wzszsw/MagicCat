"""连接配置与独立分组索引服务门面。"""

from __future__ import annotations

from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.storage import home_dir
from magiccat.storage.profile_store import JsonProfileStore


class ProfileStore:
    """连接配置存储（逐连接 JSON + 独立组索引）。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else home_dir()
        self._json = JsonProfileStore(self.root)

    @classmethod
    def default(cls) -> ProfileStore:
        return cls(home_dir())

    def load(self) -> list[ConnectionProfile]:
        return self._json.load()

    def save_profile(self, profile: ConnectionProfile) -> None:
        self._json.save_profile(profile)

    def delete_profile(self, profile_id: str) -> None:
        self._json.delete_profile(profile_id)

    def profile_path(self, profile_id: str) -> Path:
        return self._json.profile_path(profile_id)

    def load_groups(self) -> list[dict[str, object]]:
        return self._json.load_groups()

    def save_groups(self, groups: list[dict[str, object]]) -> None:
        self._json.save_groups(groups)

    @property
    def config_path(self) -> Path:
        """当前连接配置目录，供信息面板等只读展示。"""
        return self._json.path

    @property
    def connections_dir(self) -> Path:
        """逐连接 JSON 所在目录。"""
        return self._json.connections_dir
