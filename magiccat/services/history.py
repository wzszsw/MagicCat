"""最近执行的 SQL 历史（本地 JSON，最多保留 RECENT_LIMIT 条）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

RECENT_LIMIT = 50


class HistoryStore:
    def __init__(self, root: Path) -> None:
        self.file = root / "history.json"

    @classmethod
    def default(cls) -> HistoryStore:
        from magiccat.services.profile_store import _default_root

        return cls(_default_root())

    def load(self) -> list[str]:
        if not self.file.exists():
            return []
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return [str(s) for s in data.get("recent", [])]
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("history.json 读取失败: %s", exc)
            return []

    def push(self, sql: str) -> None:
        sql = sql.strip()
        if not sql:
            return
        recent = [s for s in self.load() if s != sql]
        recent.insert(0, sql)
        self.save(recent[:RECENT_LIMIT])

    def save(self, recent: list[str]) -> None:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"recent": recent}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.file)
        except OSError as exc:
            logger.warning("history 写入失败: %s", exc)
