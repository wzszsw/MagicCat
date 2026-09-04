"""SQL 收藏夹（snippets）—— 迁移到 SQLite（favorites，kind='snippet'）。"""

from __future__ import annotations

import json
from pathlib import Path

from magiccat.storage import home_dir
from magiccat.storage.sqlite_store import SqliteStore


class SnippetStore:
    """SQL 收藏夹（SQLite favorites 实现）。接口兼容旧 SnippetStore：load()/save()。"""

    def __init__(self, root: Path) -> None:
        self._db = SqliteStore(root / "metacache.db")
        self._profile = "snippets"

    @classmethod
    def default(cls) -> SnippetStore:
        return cls(home_dir())

    def load(self) -> list[dict]:
        favs = self._db.favorites(self._profile, "snippet")
        out = []
        for f in favs:
            try:
                sql = json.loads(f["payload"]).get("sql", "")
            except (ValueError, TypeError):
                sql = ""
            if f["name"] and sql:
                out.append({"name": f["name"], "sql": sql})
        return out

    def save(self, snippets: list[dict]) -> None:
        # 全量重写：先清空该 profile 下所有 snippet 收藏
        existing = self._db.favorites(self._profile, "snippet")
        for f in existing:
            self._db.favorite_delete(self._profile, "snippet", f["name"])
        for s in snippets:
            name = str(s.get("name", ""))
            sql = str(s.get("sql", ""))
            if name and sql:
                self._db.favorite_save(self._profile, "snippet", name,
                                       json.dumps({"sql": sql}, ensure_ascii=False))
