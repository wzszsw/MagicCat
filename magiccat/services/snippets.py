"""SQL 收藏夹（snippets）：本地 JSON（MAGICCAT_HOME/snippets.json）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SnippetStore:
    def __init__(self, root: Path) -> None:
        self.file = root / "snippets.json"

    @classmethod
    def default(cls) -> SnippetStore:
        from magiccat.services.profile_store import _default_root

        return cls(_default_root())

    def load(self) -> list[dict]:
        if not self.file.exists():
            return []
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            items = data.get("snippets", [])
            return [{"name": str(s.get("name", "")), "sql": str(s.get("sql", ""))}
                    for s in items if s.get("name") and s.get("sql")]
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("snippets.json 读取失败: %s", exc)
            return []

    def save(self, snippets: list[dict]) -> None:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"snippets": snippets}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.file)
        except OSError as exc:
            logger.warning("snippets 写入失败: %s", exc)
