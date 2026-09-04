"""连接配置模型。

约定：password 在内存对象里是明文（仅在打开连接时使用一次）；
持久化时由 ProfileStore 加密（Windows DPAPI），文件里永不明文。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

DEFAULT_GROUP = "默认分组"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class ConnectionProfile:
    name: str
    host: str = "127.0.0.1"
    port: int = 3306
    username: str = "root"
    password: str = ""
    database: str = ""
    group: str = DEFAULT_GROUP
    provider_key: str = "mysql"   # 方言/驱动 key（见 services/dialects.py）
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()

    @property
    def display_name(self) -> str:
        suffix = f" ({self.host}:{self.port})"
        return self.name + ("" if suffix in self.name else suffix)

    def to_dict(self) -> dict:
        """序列化（不含明文密码；密码由 ProfileStore 加密后单独落盘）。"""
        return {
            "id": self.id,
            "name": self.name,
            "group": self.group,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "database": self.database,
            "provider_key": self.provider_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict, password: str = "") -> ConnectionProfile:
        return cls(
            id=data["id"],
            name=data["name"],
            group=data.get("group", DEFAULT_GROUP),
            host=data.get("host", "127.0.0.1"),
            port=int(data.get("port", 3306)),
            username=data.get("username", "root"),
            database=data.get("database", ""),
            provider_key=data.get("provider_key", "mysql"),
            password=password,
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
        )
