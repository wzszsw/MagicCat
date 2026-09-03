"""表数据服务（M4）：分页读取 + 主键定位的增删改。值统一为 str|None 传输。"""

from __future__ import annotations

import json

import jpype

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.runtime import get_runtime


def to_java_string_array(values: list | None):
    """Python list[str|None] -> java.lang.String[]（JPype 不做隐式数组转换）。"""
    if values is None:
        return None
    arr = jpype.JArray(jpype.JString)(len(values))
    for i, v in enumerate(values):
        arr[i] = None if v is None else jpype.JString(str(v))
    return arr


class DataService:
    def __init__(self, connections: ConnectionService) -> None:
        self._connections = connections

    def _ensure_open(self, profile: ConnectionProfile) -> None:
        if not self._connections.is_open(profile.id):
            self._connections.open(profile)

    def _api(self):
        return get_runtime().jclass("com.magiccat.bridge.TableDataApi")

    def load_page(self, profile: ConnectionProfile, schema: str, table: str,
                  offset: int = 0, limit: int = 100,
                  order_by: str | None = None, where: str | None = None) -> dict:
        """返回 {columns, rows, total, pk, truncated}。"""
        self._ensure_open(profile)
        raw = self._api().page(profile.id, schema, table, int(offset), int(limit),
                               order_by or "", where or "")
        return json.loads(raw)

    def primary_key(self, profile: ConnectionProfile, schema: str, table: str) -> list[str]:
        self._ensure_open(profile)
        raw = self._api().primaryKey(profile.id, schema, table)
        return list(raw)

    def update_row(self, profile: ConnectionProfile, schema: str, table: str,
                   pk_cols: list[str], pk_vals: list, set_cols: list[str],
                   set_vals: list) -> int:
        self._ensure_open(profile)
        return int(self._api().updateRow(
            profile.id, schema, table,
            to_java_string_array(pk_cols), to_java_string_array(pk_vals),
            to_java_string_array(set_cols), to_java_string_array(set_vals)))

    def delete_row(self, profile: ConnectionProfile, schema: str, table: str,
                   pk_cols: list[str], pk_vals: list) -> int:
        self._ensure_open(profile)
        return int(self._api().deleteRow(profile.id, schema, table,
                                         to_java_string_array(pk_cols),
                                         to_java_string_array(pk_vals)))

    def insert_row(self, profile: ConnectionProfile, schema: str, table: str,
                   cols: list[str], vals: list) -> int:
        self._ensure_open(profile)
        return int(self._api().insertRow(profile.id, schema, table,
                                         to_java_string_array(cols),
                                         to_java_string_array(vals)))
