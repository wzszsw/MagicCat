"""具名 SQL 查询库（对标 Navicat “查询”抽象，本地存储）。

- 每个连接（profile）一份：MAGICCAT_HOME/queries/<profile_id>.json
- 条目：{name, schema(保存位置里的数据库), content, updated_at}
- 独立于数据库（可离线管理），打开后由编辑器绑定当前连接执行。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff ]")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class QueryLibrary:
    def __init__(self, root: Path) -> None:
        self.dir = root / "queries"
        self._lock = threading.Lock()

    @classmethod
    def default(cls) -> QueryLibrary:
        from magiccat.services.profile_store import _default_root

        return cls(_default_root())

    def _file(self, profile_id: str) -> Path:
        return self.dir / f"{profile_id}.json"

    def list(self, profile_id: str) -> list[dict]:
        """返回该连接下的查询列表（含 name/schema/updated_at，不含 content）。"""
        with self._lock:
            return [{"name": q["name"], "schema": q.get("schema", ""),
                     "updated_at": q.get("updated_at", "")}
                    for q in self._items(profile_id)]

    def get(self, profile_id: str, name: str) -> dict | None:
        with self._lock:
            for q in self._items(profile_id):
                if q["name"] == name:
                    return q
            return None

    def save(self, profile_id: str, name: str, content: str, schema: str = "") -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("查询名称不能为空")
        with self._lock:
            items = self._items(profile_id)
            for q in items:
                if q["name"] == name:
                    q.update({"content": content, "schema": schema,
                              "updated_at": _now()})
                    self._write(profile_id, items)
                    return
            items.append({"name": name, "schema": schema,
                          "content": content, "updated_at": _now()})
            self._write(profile_id, items)

    def delete(self, profile_id: str, name: str) -> bool:
        with self._lock:
            items = self._items(profile_id)
            new = [q for q in items if q["name"] != name]
            if len(new) == len(items):
                return False
            self._write(profile_id, new)
            return True

    def _items(self, profile_id: str) -> list[dict]:
        path = self._file(profile_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [q for q in data.get("queries", []) if q.get("name")]
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("查询库读取失败(%s): %s", profile_id, exc)
            return []

    def _write(self, profile_id: str, items: list[dict]) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self._file(profile_id)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"queries": items}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            logger.warning("查询库写入失败(%s): %s", profile_id, exc)


def sanitize_name(name: str) -> str:
    """用于文件名安全显示（不落盘文件名时无需强约束；防注入用）。"""
    return _NAME_RE.sub("_", name)
