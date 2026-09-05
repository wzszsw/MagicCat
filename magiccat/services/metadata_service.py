"""元数据服务：把 Java MetadataApi 返回的 JSON 表转成 list[dict]。需连接已打开。"""

from __future__ import annotations

import json

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.runtime import get_runtime


class MetadataService:
    def __init__(self, connections: ConnectionService) -> None:
        self._connections = connections

    # ---- 底层 ----
    def _ensure_open(self, profile: ConnectionProfile) -> None:
        if not self._connections.is_open(profile.id):
            self._connections.open(profile)

    @staticmethod
    def _to_rows(json_text: str) -> list[dict]:
        """{"columns":[...],"rows":[[...]]} -> [ {col: value|null}, ... ]（值统一为 str|None）。"""
        data = json.loads(json_text)
        cols = data["columns"]
        return [dict(zip(cols, row)) for row in data["rows"]]

    def _meta(self, profile: ConnectionProfile, method: str, *args) -> list[dict]:
        self._ensure_open(profile)
        runtime = get_runtime()
        Meta = runtime.jclass("com.magiccat.bridge.MetadataApi")
        out = getattr(Meta, method)(profile.id, *args)
        return self._to_rows(out)

    # ---- 对象树查询 ----
    def databases(self, profile: ConnectionProfile) -> list[dict]:
        return self._meta(profile, "databases")

    def tables(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "tables", schema)

    def schema_tables(self, profile: ConnectionProfile, schema: str,
                      database: str = "") -> list[dict]:
        """全库表信息一次批查（表对象页；含 engine/rows/comment，避免 N+1）。

        PostgreSQL/GaussDB 使用目标 Catalog 上的标准信息模式查询；不能落到
        MySQL 专用 ``TABLE_ROWS AS `rows``` 语法，否则 openGauss 会在反引号处报错。
        """
        if profile.is_postgres:
            return self.schema_tables_in_database(profile, database, schema)
        return self._meta(profile, "schemaTables", schema)

    def schema_tables_in_database(self, profile: ConnectionProfile, database: str,
                                  schema: str) -> list[dict]:
        return self._meta(profile, "schemaTablesInDatabase", database, schema)

    def schemas(self, profile: ConnectionProfile, database: str) -> list[dict]:
        """PostgreSQL：某 database 下的 schema 列表（须临时连到该库）。"""
        return self._meta(profile, "schemas", database)

    def tables_in_database(self, profile: ConnectionProfile, database: str,
                           schema: str) -> list[dict]:
        """PostgreSQL：某 database.schema 下的表/视图。"""
        return self._meta(profile, "tablesInDatabase", database, schema)

    def routines_in_database(self, profile: ConnectionProfile, database: str,
                             schema: str) -> list[dict]:
        """PostgreSQL：某 database.schema 下的例程（函数/过程）。"""
        return self._meta(profile, "routinesInDatabase", database, schema)

    def sequences_in_database(self, profile: ConnectionProfile, database: str,
                              schema: str) -> list[dict]:
        """PostgreSQL：某 database.schema 下的序列列表。"""
        return self._meta(profile, "sequencesInDatabase", database, schema)

    def routines(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "routines", schema)

    def triggers(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "triggers", schema)

    def columns(self, profile: ConnectionProfile, schema: str, table: str,
                database: str = "") -> list[dict]:
        return self._meta(profile, "columns", database, schema, table)

    def indexes(self, profile: ConnectionProfile, schema: str, table: str) -> list[dict]:
        return self._meta(profile, "indexes", schema, table)

    def foreign_keys(self, profile: ConnectionProfile, schema: str, table: str) -> list[dict]:
        return self._meta(profile, "foreignKeys", schema, table)

    # ---- 全库批查（避免“逐表循环查”的 N+1，结果按 table_name 归组由调用方聚合） ----
    def schema_columns(self, profile: ConnectionProfile, schema: str,
                       database: str = "") -> list[dict]:
        if profile.is_postgres:
            return self.schema_columns_in_database(profile, database, schema)
        return self._meta(profile, "schemaColumns", schema)

    def schema_columns_in_database(self, profile: ConnectionProfile, database: str,
                                   schema: str) -> list[dict]:
        return self._meta(profile, "schemaColumnsInDatabase", database, schema)

    def schema_indexes(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "schemaIndexes", schema)

    def schema_foreign_keys(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "schemaForeignKeys", schema)
