"""查询服务：把一段 SQL 切分为语句逐条执行，返回结构化结果列表。

结果项结构（dict）：
    {"kind": "query",  "sql", "columns": [...], "rows": [[...]], "time_ms", "truncated"}
    {"kind": "update", "sql", "affected": N, "time_ms"}
    {"kind": "error",  "sql", "message", "time_ms", "cancelled": bool}

取消：每次 execute() 生成唯一 run_token；Java 侧按令牌注册当前 Statement。
用户点“取消”时 cancel_all() 会：
  1) 标记这些 run_token 为已取消；
  2) 调用 ConnectionRegistry.cancelToken 中断正在执行的语句；
被中断的语句在 worker 线程抛错后，本服务识别取消标记并中止后续语句。
"""

from __future__ import annotations

import json
import threading
import time
import uuid

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.runtime import get_runtime
from magiccat.services.sql_text import split_sql_statements
from magiccat.utils.errors import format_exc


class QueryService:
    def __init__(self, connections: ConnectionService, max_rows: int = 2000) -> None:
        self._connections = connections
        self.max_rows = max_rows
        self._lock = threading.Lock()
        self._active_tokens: set[str] = set()
        self._cancelled_tokens: set[str] = set()

    # ---- 取消 ----
    def active_count(self) -> int:
        with self._lock:
            return len(self._active_tokens)

    def cancel_all(self) -> int:
        """取消全部在途执行；返回取消的运行数。"""
        with self._lock:
            tokens = list(self._active_tokens)
            self._cancelled_tokens.update(tokens)
        if tokens:
            runtime = get_runtime()
            Executor = runtime.jclass("com.magiccat.bridge.ConnectionRegistry")
            for token in tokens:
                Executor.cancelToken(token)
        return len(tokens)

    # ---- 执行 ----
    def execute(
        self,
        profile: ConnectionProfile,
        sql: str,
        catalog: str | None = None,
        schema: str | None = None,
        *,
        database: str | None = None,
    ) -> list[dict]:
        """执行 SQL，并可为本次执行指定 JDBC catalog/schema 上下文。

        ``database`` 是 ``catalog`` 的兼容别名，方便沿用元数据层已有命名。
        上下文只传给当前执行借出的 JDBC 连接，不会生成或注入 ``USE``。
        MySQL/MariaDB 没有 JDBC schema 语义，因此始终向 Java 层传 ``null``。
        """
        if database is not None:
            if catalog is not None and catalog != database:
                raise ValueError("catalog 与 database 不能同时指定不同值")
            catalog = database
        # ``None`` means no explicit workspace context; keep the legacy overload in
        # that case. An explicitly empty catalog is still a context request, allowing
        # the Java side to restore the profile's configured catalog deterministically.
        catalog_value = "" if catalog is None else str(catalog).strip()
        schema_value = (
            str(schema).strip() if profile.is_postgres and schema is not None else None
        )
        context_requested = catalog is not None or schema is not None
        statements = [s for s in split_sql_statements(sql) if s.strip()]
        if not statements:
            return []
        if not self._connections.is_open(profile.id):
            self._connections.open(profile)

        run_token = uuid.uuid4().hex
        with self._lock:
            self._active_tokens.add(run_token)
            self._cancelled_tokens.discard(run_token)

        results: list[dict] = []
        try:
            runtime = get_runtime()
            Executor = runtime.jclass("com.magiccat.bridge.ConnectionRegistry")
            for stmt in statements:
                started = time.perf_counter()
                try:
                    if context_requested:
                        raw = Executor.executeCancelable(
                            profile.id, catalog_value, schema_value,
                            stmt, self.max_rows, run_token)
                    else:
                        # 保留旧入口，供非查询工作区服务和旧插件继续使用连接默认上下文。
                        raw = Executor.executeCancelable(
                            profile.id, stmt, self.max_rows, run_token)
                    data = json.loads(raw)
                    data["sql"] = stmt
                    data["time_ms"] = round((time.perf_counter() - started) * 1000, 1)
                    if data["kind"] == "query":
                        data["truncated"] = len(data["rows"]) >= self.max_rows
                except Exception as exc:  # noqa: BLE001 —— 单条错误需上报并可继续
                    data = {
                        "kind": "error",
                        "sql": stmt,
                        "message": format_exc(exc),
                        "time_ms": round((time.perf_counter() - started) * 1000, 1),
                        "cancelled": False,
                    }
                    with self._lock:
                        if run_token in self._cancelled_tokens:
                            data["message"] = "执行已取消（用户停止）"
                            data["cancelled"] = True
                            results.append(data)
                            break
                results.append(data)
        finally:
            with self._lock:
                self._active_tokens.discard(run_token)
                self._cancelled_tokens.discard(run_token)
        return results
