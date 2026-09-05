"""具名查询库 —— 迁移到「.sql 文件 + SQLite 收藏」（对标 Navicat）。

- 查询内容：`<MAGICCAT_HOME>/<provider>/Servers/<connection>/<database>/<schema>/<name>.sql`。
- 元数据（名称/所属 database/schema/更新时间）：SQLite favorites（kind='query'）。
- 兼容旧接口 list/get/save/delete；**不兼容旧 queries/<profile_id>.json**（弃用、不迁移）。
"""

from __future__ import annotations

from pathlib import Path

from magiccat.storage import home_dir
from magiccat.storage.query_store import QueryStore


class QueryLibrary:
    """具名查询库（对象页/树联动）。接口兼容旧 QueryLibrary。"""

    def __init__(self, root: Path) -> None:
        self._store = QueryStore(root=root)

    @classmethod
    def default(cls) -> QueryLibrary:
        return cls(home_dir())

    def list(self, profile_id: str) -> list[dict]:
        return self._store.list(profile_id)

    def get(self, profile_id: str, name: str) -> dict | None:
        return self._store.get(profile_id, name)

    def save(self, profile_id: str, name: str, content: str, schema: str = "",
             database: str = "") -> None:
        self._store.save(profile_id, name, content, schema=schema, database=database)

    def delete(self, profile_id: str, name: str) -> bool:
        return self._store.delete(profile_id, name)
