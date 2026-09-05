"""连接管理服务：连接配置 CRUD + 打开/关闭/测试连接（线程内调用，UI 需再包一层异步）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.services.profile_store import ProfileStore
from magiccat.services.runtime import get_runtime
from magiccat.services.settings import AppSettings

logger = logging.getLogger(__name__)


class ConnectionService:
    def __init__(self, store: ProfileStore | None = None) -> None:
        self._store = store or ProfileStore.default()
        self._profiles: list[ConnectionProfile] = self._store.load()
        self._open: set[str] = set()

    # ---- 配置 CRUD ----
    @property
    def profiles(self) -> list[ConnectionProfile]:
        return list(self._profiles)

    @property
    def config_path(self) -> Path:
        """连接配置实际落盘位置。"""
        return self._store.config_path

    @property
    def groups(self) -> list[str]:
        seen: list[str] = []
        for p in self._profiles:
            if p.group not in seen:
                seen.append(p.group)
        return seen

    def get(self, profile_id: str) -> ConnectionProfile | None:
        return next((p for p in self._profiles if p.id == profile_id), None)

    def add(self, profile: ConnectionProfile) -> None:
        self._profiles.append(profile)
        self._save()

    def update(self, profile: ConnectionProfile) -> None:
        profile.touch()
        for i, p in enumerate(self._profiles):
            if p.id == profile.id:
                self._profiles[i] = profile
                break
        else:
            self._profiles.append(profile)
        self._save()

    def remove(self, profile_id: str) -> None:
        self.close(profile_id)
        self._profiles = [p for p in self._profiles if p.id != profile_id]
        self._save()

    def _save(self) -> None:
        self._store.save(self._profiles)

    # ---- 连接生命周期 ----
    @property
    def open_ids(self) -> set[str]:
        return set(self._open)

    def is_open(self, profile_id: str) -> bool:
        return profile_id in self._open

    def open(self, profile: ConnectionProfile) -> str:
        """打开连接池并返回数据库版本；已在打开状态则直接 ping。"""
        runtime = get_runtime()
        Registry = runtime.jclass("com.magiccat.bridge.ConnectionRegistry")
        driver_jar = self._driver_jar(profile)
        Registry.open(profile.id, profile.provider_key, profile.host, profile.port,
                      profile.database, profile.username, profile.password, driver_jar)
        version = Registry.ping(profile.id)
        self._open.add(profile.id)
        logger.info("已打开连接 [%s] -> %s", profile.name, version)
        return version

    def close(self, profile_id: str) -> None:
        if profile_id not in self._open:
            return
        runtime = get_runtime()
        runtime.jclass("com.magiccat.bridge.ConnectionRegistry").close(profile_id)
        self._open.discard(profile_id)

    def close_all(self) -> None:
        for pid in list(self._open):
            self.close(pid)

    def test(self, profile: ConnectionProfile) -> str:
        """测试连接（一次性 JDBC 连接，不影响已打开的长期连接池）。"""
        runtime = get_runtime()
        Registry = runtime.jclass("com.magiccat.bridge.ConnectionRegistry")
        driver_jar = self._driver_jar(profile)
        return Registry.test(profile.id, profile.provider_key, profile.host, profile.port,
                             profile.database, profile.username, profile.password, driver_jar)

    @staticmethod
    def _driver_jar(profile: ConnectionProfile) -> str:
        if profile.provider_key != "gaussdb":
            return ""
        path = str(AppSettings.default().get("gaussdb_driver_jar", "") or "").strip()
        if not path:
            raise ValueError("GaussDB 尚未配置 JDBC 驱动，请打开“工具 → 环境”指定本机 gaussdbjdbc.jar。")
        if not Path(path).is_file():
            raise FileNotFoundError(f"GaussDB JDBC 驱动不存在：{path}")
        return path

    def server_info(self, profile: ConnectionProfile) -> dict:
        """基于标准 JDBC DatabaseMetaData 的产品/版本/URL/用户等（需已打开）。"""
        if not self.is_open(profile.id):
            self.open(profile)
        raw = get_runtime().jclass("com.magiccat.bridge.ServerInfoApi").info(profile.id)
        return json.loads(raw)
