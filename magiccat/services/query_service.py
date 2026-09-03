"""查询服务：把一段 SQL 切分为语句逐条执行，返回结构化结果列表。

结果项结构（dict）：
    {"kind": "query",  "sql", "columns": [...], "rows": [[...]], "time_ms", "truncated"}
    {"kind": "update", "sql", "affected": N, "time_ms"}
    {"kind": "error",  "sql", "message", "time_ms"}
"""

from __future__ import annotations

import json
import time

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.runtime import get_runtime
from magiccat.services.sql_text import split_sql_statements


class QueryService:
    def __init__(self, connections: ConnectionService, max_rows: int = 2000) -> None:
        self._connections = connections
        self.max_rows = max_rows

    def execute(self, profile: ConnectionProfile, sql: str) -> list[dict]:
        """按语句切分逐条执行；单条失败不影响后续语句（与 Navicat 行为一致）。"""
        statements = [s for s in split_sql_statements(sql) if s.strip()]
        if not statements:
            return []
        if not self._connections.is_open(profile.id):
            self._connections.open(profile)

        results: list[dict] = []
        runtime = get_runtime()
        Executor = runtime.jclass("com.magiccat.bridge.ConnectionRegistry")
        for stmt in statements:
            started = time.perf_counter()
            try:
                raw = Executor.execute(profile.id, stmt, self.max_rows)
                data = json.loads(raw)
                data["sql"] = stmt
                data["time_ms"] = round((time.perf_counter() - started) * 1000, 1)
                if data["kind"] == "query":
                    data["truncated"] = len(data["rows"]) >= self.max_rows
            except Exception as exc:  # noqa: BLE001 —— 单条语句错误需逐条上报
                data = {
                    "kind": "error",
                    "sql": stmt,
                    "message": f"{type(exc).__name__}: {exc}",
                    "time_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            results.append(data)
        return results
