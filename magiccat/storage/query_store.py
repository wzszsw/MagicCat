"""具名查询（SQL）的本地存储——对标 Navicat：查询内容存 `.sql` 文件，元数据存 SQLite 收藏。

- 目录结构：`<root>/queries/<profile_id>/<schema>/<name>.sql`（与 Navicat 按 连接/库 组织一致）。
- 元数据（名称/所属 schema/更新时间）存 SQLite `favorites`（kind='query'），内容在 .sql 文件。
- 不兼容旧 queries/<profile_id>.json：旧文件弃用、不迁移。
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from magiccat.storage import home_dir
from magiccat.storage.sqlite_store import SqliteStore

_NAME_RE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff ]")


def _safe(name: str) -> str:
    return _NAME_RE.sub("_", name).strip() or "_"


class QueryStore:
    """具名查询：内容存 .sql，元数据存 SQLite favorites。"""

    def __init__(self, root: Path | None = None, sqlite: SqliteStore | None = None) -> None:
        self.root = root or home_dir()
        self.dir = self.root / "queries"
        # 元数据 SQLite 与 root 同源（隔离），否则测试会读到全局收藏
        self._sqlite = sqlite or SqliteStore(self.root / "metacache.db")
        self._lock = threading.Lock()

    @classmethod
    def default(cls) -> QueryStore:
        return cls()

    def _file(self, profile_id: str, schema: str, name: str) -> Path:
        return self.dir / _safe(profile_id) / _safe(schema) / f"{_safe(name)}.sql"

    def list(self, profile_id: str) -> list[dict]:
        """返回该连接下的查询列表（含 name/schema/updated_at）。"""
        with self._lock:
            return [{"name": f["name"], "schema": _schema_of(f["payload"]),
                     "updated_at": _updated_of(f["payload"])}
                    for f in self._sqlite.favorites(profile_id, "query")]

    def get(self, profile_id: str, name: str) -> dict | None:
        with self._lock:
            favs = self._sqlite.favorites(profile_id, "query")
            for f in favs:
                if f["name"] != name:
                    continue
                schema = _schema_of(f["payload"])
                path = self._file(profile_id, schema, name)
                content = path.read_text(encoding="utf-8") if path.exists() else ""
                return {"name": name, "schema": schema,
                        "content": content, "updated_at": _updated_of(f["payload"])}
            return None

    def save(self, profile_id: str, name: str, content: str, schema: str = "") -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("查询名称不能为空")
        with self._lock:
            path = self._file(profile_id, schema, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self._sqlite.favorite_save(profile_id, "query", name,
                                       _payload(schema))

    def delete(self, profile_id: str, name: str) -> bool:
        with self._lock:
            # 找到该查询的 schema 以定位 .sql 文件并删除
            target = None
            for f in self._sqlite.favorites(profile_id, "query"):
                if f["name"] == name:
                    target = _schema_of(f["payload"])
                    break
            ok = self._sqlite.favorite_delete(profile_id, "query", name)
            if target is not None:
                path = self._file(profile_id, target, name)
                try:
                    path.unlink()
                except OSError:
                    pass
            return ok


def _payload(schema: str) -> str:
    import json
    return json.dumps({"schema": schema})


def _schema_of(payload: str) -> str:
    import json
    try:
        return json.loads(payload).get("schema", "")
    except (ValueError, TypeError):
        return ""


def _updated_of(payload: str) -> str:
    import json
    try:
        return str(json.loads(payload).get("updated_at", ""))
    except (ValueError, TypeError):
        return ""
