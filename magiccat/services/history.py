"""最近执行的 SQL 历史 —— 迁移到 SQLite（metacache.db）。"""

from __future__ import annotations

from pathlib import Path

from magiccat.storage import home_dir
from magiccat.storage.sqlite_store import SqliteStore

RECENT_LIMIT = 50


class HistoryStore:
    """最近 SQL 历史（SQLite 实现）。接口兼容旧 HistoryStore：load()/push()/save()。"""

    def __init__(self, root: Path) -> None:
        self._sqlite = SqliteStore(root / "metacache.db")

    @classmethod
    def default(cls) -> HistoryStore:
        return cls(home_dir())

    def load(self) -> list[str]:
        return self._sqlite.history(RECENT_LIMIT)

    def push(self, sql: str) -> None:
        self._sqlite.history_push(sql)
