"""SQLite 本地库（metacache.db）：元数据缓存 / 查询历史 / 收藏 / 窗口状态。

对标 Navicat 用 SQLite 存"简单数据/缓存/历史/索引"的做法：
- 元数据缓存：按 (profile, schema, object_type) 缓存，带过期时间戳。
- 查询历史：最近执行的 SQL（去重、限条数）。
- 收藏：具名收藏项。
- 窗口状态：主窗口几何等键值。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS metadata_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT,
    created_at REAL,
    ttl REAL
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sql_text TEXT UNIQUE,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT,
    kind TEXT,
    name TEXT,
    payload TEXT,
    created_at REAL,
    UNIQUE(profile_id, kind, name)
);
"""


class SqliteStore:
    """单个 SQLite 库的封装。线程安全（锁）。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.path), timeout=10)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_SCHEMA)
            con.commit()
        finally:
            con.close()

    @classmethod
    def default(cls) -> SqliteStore:
        from magiccat.storage import home_dir

        return cls(home_dir() / "metacache.db")

    @contextmanager
    def _session(self):
        """打开一个连接并保证使用后关闭（sqlite3 with 只 commit 不 close）。"""
        con = sqlite3.connect(str(self.path), timeout=10)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ---- kv（窗口状态/简单键值） ----
    def kv_get(self, key: str, default: str | None = None) -> str | None:
        with self._lock, self._session() as con:
            row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return row[0] if row else default

    def kv_set(self, key: str, value: str) -> None:
        with self._lock, self._session() as con:
            con.execute("INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                        "updated_at=excluded.updated_at",
                        (key, value, time.time()))

    # ---- 元数据缓存 ----
    def cache_get(self, cache_key: str, ttl: float = 300.0):
        with self._lock, self._session() as con:
            row = con.execute("SELECT payload, created_at, ttl FROM metadata_cache "
                              "WHERE cache_key=?", (cache_key,)).fetchone()
        if not row:
            return None
        payload, created_at, saved_ttl = row
        if time.time() - created_at > (saved_ttl or ttl):
            return None
        return json.loads(payload)

    def cache_set(self, cache_key: str, payload, ttl: float = 300.0) -> None:
        with self._lock, self._session() as con:
            con.execute("INSERT INTO metadata_cache(cache_key,payload,created_at,ttl) "
                        "VALUES(?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET "
                        "payload=excluded.payload, created_at=excluded.created_at, "
                        "ttl=excluded.ttl",
                        (cache_key, json.dumps(payload, ensure_ascii=False),
                         time.time(), ttl))

    # ---- 历史 ----
    def history(self, limit: int = 50) -> list[str]:
        with self._lock, self._session() as con:
            rows = con.execute("SELECT sql_text FROM history "
                               "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [r[0] for r in rows]

    def history_push(self, sql: str) -> None:
        sql = sql.strip()
        if not sql:
            return
        with self._lock, self._session() as con:
            # 若已存在同内容，删旧再插，保证最新排前
            con.execute("DELETE FROM history WHERE sql_text=?", (sql,))
            con.execute("INSERT INTO history(sql_text,created_at) VALUES(?,?)",
                        (sql, time.time()))

    # ---- 收藏 ----
    def favorites(self, profile_id: str, kind: str) -> list[dict]:
        with self._lock, self._session() as con:
            rows = con.execute("SELECT name, payload FROM favorites "
                               "WHERE profile_id=? AND kind=? ORDER BY name",
                               (profile_id, kind)).fetchall()
            return [{"name": r[0], "payload": r[1]} for r in rows]

    def favorite_save(self, profile_id: str, kind: str, name: str, payload: str) -> None:
        with self._lock, self._session() as con:
            con.execute("INSERT INTO favorites(profile_id,kind,name,payload,created_at) "
                        "VALUES(?,?,?,?,?) ON CONFLICT(profile_id,kind,name) DO UPDATE SET "
                        "payload=excluded.payload, created_at=excluded.created_at",
                        (profile_id, kind, name, payload, time.time()))

    def favorite_delete(self, profile_id: str, kind: str, name: str) -> bool:
        with self._lock, self._session() as con:
            cur = con.execute("DELETE FROM favorites WHERE profile_id=? AND kind=? AND name=?",
                              (profile_id, kind, name))
            return cur.rowcount > 0
