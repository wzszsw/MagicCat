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

    def routines(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "routines", schema)

    def triggers(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "triggers", schema)

    def columns(self, profile: ConnectionProfile, schema: str, table: str) -> list[dict]:
        return self._meta(profile, "columns", schema, table)

    def indexes(self, profile: ConnectionProfile, schema: str, table: str) -> list[dict]:
        return self._meta(profile, "indexes", schema, table)

    def foreign_keys(self, profile: ConnectionProfile, schema: str, table: str) -> list[dict]:
        return self._meta(profile, "foreignKeys", schema, table)

    # ---- 全库批查（避免“逐表循环查”的 N+1，结果按 table_name 归组由调用方聚合） ----
    def schema_columns(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "schemaColumns", schema)

    def schema_indexes(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "schemaIndexes", schema)

    def schema_foreign_keys(self, profile: ConnectionProfile, schema: str) -> list[dict]:
        return self._meta(profile, "schemaForeignKeys", schema)
