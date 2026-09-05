"""具名查询（SQL）的本地存储——对标 Navicat：查询内容存 `.sql` 文件，元数据存 SQLite 收藏。

- 目录结构：`<root>/<provider>/Servers/<connection>/<database>/<schema>/<name>.sql`；
  MySQL 没有独立 schema，省略 schema 层。
- 元数据（名称/所属 database/schema/更新时间）存 SQLite `favorites`（kind='query'），内容在 .sql 文件。
- 不兼容旧 queries/<profile_id>.json：旧文件弃用、不迁移。
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from magiccat.storage import home_dir
from magiccat.storage.profile_store import JsonProfileStore
from magiccat.storage.sqlite_store import SqliteStore

_NAME_RE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff ]")


def _safe(name: str) -> str:
    return _NAME_RE.sub("_", name).strip() or "_"


class QueryStore:
    """具名查询：内容存 .sql，元数据存 SQLite favorites。"""

    def __init__(self, root: Path | None = None, sqlite: SqliteStore | None = None) -> None:
        self.root = root or home_dir()
        self._profiles = JsonProfileStore(self.root)
        # 元数据 SQLite 与 root 同源（隔离），否则测试会读到全局收藏
        self._sqlite = sqlite or SqliteStore(self.root / "metacache.db")
        self._lock = threading.Lock()

    @classmethod
    def default(cls) -> QueryStore:
        return cls()

    def _connection_dir(self, profile_id: str) -> Path:
        """按逐连接配置定位 Navicat 式连接目录。"""
        profile = next((p for p in self._profiles.load()
                        if p.id == profile_id), None)
        if profile is None:
            raise FileNotFoundError(f"连接配置不存在：{profile_id}")
        provider_dir = JsonProfileStore._safe_provider_dir(profile.provider_key)
        connection_stem = JsonProfileStore._safe_stem(profile.name)
        return (self.root / provider_dir / "Servers"
                / connection_stem)

    def _file(self, profile_id: str, database: str, schema: str, name: str) -> Path:
        path = self._connection_dir(profile_id) / _safe(database)
        if schema:
            path /= _safe(schema)
        return path / f"{_safe(name)}.sql"

    @staticmethod
    def _scope(payload: str) -> tuple[str, str]:
        import json

        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return "", ""
        if not isinstance(data, dict):
            return "", ""
        return (str(data.get("database", "") or ""),
                str(data.get("schema", "") or ""))

    def list(self, profile_id: str) -> list[dict]:
        """返回该连接下的查询列表（含 name/database/schema/updated_at）。"""
        with self._lock:
            return [{"name": f["name"],
                     "database": self._scope(f["payload"])[0],
                     "schema": self._scope(f["payload"])[1],
                     "updated_at": _updated_of(f["payload"])}
                    for f in self._sqlite.favorites(profile_id, "query")]

    def get(self, profile_id: str, name: str) -> dict | None:
        with self._lock:
            favs = self._sqlite.favorites(profile_id, "query")
            for f in favs:
                if f["name"] != name:
                    continue
                database, schema = self._scope(f["payload"])
                path = self._file(profile_id, database, schema, name)
                content = path.read_text(encoding="utf-8") if path.exists() else ""
                return {"name": name, "database": database, "schema": schema,
                        "content": content, "updated_at": _updated_of(f["payload"])}
            return None

    def save(self, profile_id: str, name: str, content: str, schema: str = "",
             database: str = "") -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("查询名称不能为空")
        database = (database or "").strip()
        schema = (schema or "").strip()
        with self._lock:
            path = self._file(profile_id, database, schema, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self._sqlite.favorite_save(profile_id, "query", name,
                                       _payload(database, schema))

    def delete(self, profile_id: str, name: str) -> bool:
        with self._lock:
            # 找到该查询的 schema 以定位 .sql 文件并删除
            target: tuple[str, str] | None = None
            for f in self._sqlite.favorites(profile_id, "query"):
                if f["name"] == name:
                    target = self._scope(f["payload"])
                    break
            ok = self._sqlite.favorite_delete(profile_id, "query", name)
            if target is not None:
                path = self._file(profile_id, target[0], target[1], name)
                try:
                    path.unlink()
                except OSError:
                    pass
            return ok


def _payload(database: str, schema: str) -> str:
    import json
    return json.dumps({"database": database, "schema": schema})


def _updated_of(payload: str) -> str:
    import json
    try:
        return str(json.loads(payload).get("updated_at", ""))
    except (ValueError, TypeError):
        return ""
