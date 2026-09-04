"""应用设置 —— 迁移到 SQLite（metacache.db，kv 表）。"""

from __future__ import annotations

from pathlib import Path

from magiccat.storage import home_dir
from magiccat.storage.sqlite_store import SqliteStore

DEFAULTS = {"theme": "light"}


class AppSettings:
    """应用设置（SQLite 键值实现）。接口兼容旧 AppSettings：get()/set()。"""

    def __init__(self, root: Path) -> None:
        self._db = SqliteStore(root / "metacache.db")
        self._data: dict = dict(DEFAULTS)
        # 载入已存设置
        for key, default in DEFAULTS.items():
            v = self._db.kv_get("settings:" + key)
            if v is not None:
                try:
                    self._data[key] = type(default)(v)
                except (ValueError, TypeError):
                    self._data[key] = v

    @classmethod
    def default(cls) -> AppSettings:
        return cls(home_dir())

    def get(self, key: str, default=None):
        # 优先读 SQLite（最新值），避免内存快照过期
        v = self._db.kv_get("settings:" + key)
        if v is not None:
            try:
                return type(DEFAULTS.get(key, default))(v) if DEFAULTS.get(key) is not None else v
            except (ValueError, TypeError):
                return v
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._db.kv_set("settings:" + key, str(value))
