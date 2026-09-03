"""DDL 服务：取服务器原生 DDL + 元数据快照（供表设计器）。"""

from __future__ import annotations

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.metadata_service import MetadataService
from magiccat.services.runtime import get_runtime


class DdlService:
    def __init__(self, connections: ConnectionService,
                 metadata: MetadataService | None = None) -> None:
        self._connections = connections
        self._metadata = metadata or MetadataService(connections)

    def _ensure_open(self, profile: ConnectionProfile) -> None:
        if not self._connections.is_open(profile.id):
            self._connections.open(profile)

    def show_create(self, profile: ConnectionProfile, schema: str, table: str) -> str:
        self._ensure_open(profile)
        return get_runtime().jclass("com.magiccat.bridge.DdlApi").showCreateTable(
            profile.id, schema, table)

    def show_create_view(self, profile: ConnectionProfile, schema: str, name: str) -> str:
        self._ensure_open(profile)
        return get_runtime().jclass("com.magiccat.bridge.DdlApi").showCreateView(
            profile.id, schema, name)

    def show_create_routine(self, profile: ConnectionProfile, schema: str, name: str,
                             kind: str) -> str:
        self._ensure_open(profile)
        return get_runtime().jclass("com.magiccat.bridge.DdlApi").showCreateRoutine(
            profile.id, schema, name, kind)

    def show_create_trigger(self, profile: ConnectionProfile, schema: str, name: str) -> str:
        self._ensure_open(profile)
        return get_runtime().jclass("com.magiccat.bridge.DdlApi").showCreateTrigger(
            profile.id, schema, name)

    def snapshot(self, profile: ConnectionProfile, schema: str, table: str) -> dict:
        """列/索引/外键/原生 DDL 快照。"""
        return {
            "columns": self._metadata.columns(profile, schema, table),
            "indexes": self._metadata.indexes(profile, schema, table),
            "foreign_keys": self._metadata.foreign_keys(profile, schema, table),
            "create_sql": self.show_create(profile, schema, table),
        }
