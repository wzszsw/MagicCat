"""连接管理服务：连接配置 CRUD + 打开/关闭/测试连接（线程内调用，UI 需再包一层异步）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.services.dialects import PROVIDERS
from magiccat.services.profile_store import ProfileStore
from magiccat.services.runtime import get_runtime
from magiccat.services.settings import AppSettings

logger = logging.getLogger(__name__)


class ConnectionService:
    def __init__(self, store: ProfileStore | None = None) -> None:
        self._store = store or ProfileStore.default()
        self._profiles: list[ConnectionProfile] = self._store.load()
        self._validate_loaded_names()
        self._groups: list[dict[str, object]] = self._store.load_groups()
        self._restore_group_membership()
        self._open: set[str] = set()

    # ---- 配置 CRUD ----
    @property
    def profiles(self) -> list[ConnectionProfile]:
        return list(self._profiles)

    @property
    def config_path(self) -> Path:
        """连接配置实际落盘位置。"""
        return self._store.config_path

    def profile_config_path(self, profile_id: str) -> Path:
        return self._store.profile_path(profile_id)

    @property
    def groups(self) -> list[str]:
        return [str(group["name"]) for group in self._groups]

    def get(self, profile_id: str) -> ConnectionProfile | None:
        return next((p for p in self._profiles if p.id == profile_id), None)

    @staticmethod
    def _name_key(name: str) -> str:
        """连接名按用户可见文本去首尾空白并按大小写不敏感比较。"""
        return name.strip().casefold()

    @staticmethod
    def _ensure_provider_key(provider_key: str) -> None:
        if provider_key not in PROVIDERS:
            raise ValueError(f"不支持的数据库产品名称：{provider_key}")

    def _ensure_unique_name(
        self,
        name: str,
        provider_key: str,
        exclude_id: str | None = None,
    ) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValueError("连接名称不能为空")
        self._ensure_provider_key(provider_key)
        key = self._name_key(normalized)
        for profile in self._profiles:
            if (profile.id != exclude_id
                    and profile.provider_key == provider_key
                    and self._name_key(profile.name) == key):
                raise ValueError(
                    f"同一数据库产品内连接名称必须唯一：{provider_key} / {normalized}"
                )
        return normalized

    def validate_name(
        self,
        name: str,
        provider_key: str,
        exclude_id: str | None = None,
    ) -> str:
        """校验连接名称，可供编辑对话框在关闭前反馈重复名。"""
        return self._ensure_unique_name(name, provider_key, exclude_id)

    def _validate_loaded_names(self) -> None:
        seen: dict[tuple[str, str], str] = {}
        seen_ids: set[str] = set()
        for profile in self._profiles:
            self._ensure_provider_key(profile.provider_key)
            if profile.id in seen_ids:
                raise ValueError(f"连接配置存在重复标识：{profile.id}")
            seen_ids.add(profile.id)
            key = (profile.provider_key, self._name_key(profile.name))
            previous = seen.get(key)
            if previous is not None:
                raise ValueError(
                    f"连接配置存在同一数据库产品内重复名称："
                    f"{profile.provider_key} / {profile.name}"
                )
            seen[key] = profile.id

    def add(self, profile: ConnectionProfile) -> None:
        self._ensure_provider_key(profile.provider_key)
        profile.name = self._ensure_unique_name(profile.name, profile.provider_key)
        if self.get(profile.id) is not None:
            raise ValueError(f"连接已存在：{profile.id}")
        profile.group = None
        self._store.save_profile(profile)
        self._profiles.append(profile)

    def update(self, profile: ConnectionProfile) -> None:
        self._ensure_provider_key(profile.provider_key)
        existing = self.get(profile.id)
        profile.name = self._ensure_unique_name(
            profile.name, profile.provider_key, profile.id
        )
        if existing is not None:
            profile.group = existing.group
        profile.touch()
        self._store.save_profile(profile)
        for i, p in enumerate(self._profiles):
            if p.id == profile.id:
                self._profiles[i] = profile
                break
        else:
            self._profiles.append(profile)

    def remove(self, profile_id: str) -> None:
        self.close(profile_id)
        self._profiles = [p for p in self._profiles if p.id != profile_id]
        for group in self._groups:
            ids = group.get("profile_ids", [])
            if isinstance(ids, list):
                group["profile_ids"] = [pid for pid in ids if str(pid) != profile_id]
        self._persist_groups()
        self._store.delete_profile(profile_id)

    def _restore_group_membership(self) -> None:
        by_id = {profile.id: profile for profile in self._profiles}
        for profile in self._profiles:
            profile.group = None
        for group in self._groups:
            name = str(group.get("name", ""))
            ids = group.get("profile_ids", [])
            if not name or not isinstance(ids, list):
                continue
            for profile_id in ids:
                profile = by_id.get(str(profile_id))
                if profile is not None:
                    profile.group = name

    def _persist_groups(self) -> None:
        self._store.save_groups(self._groups)

    def add_group(self, name: str) -> None:
        name = name.strip()
        if not name or name in self.groups:
            raise ValueError("分组名称不能为空且不能重复")
        self._groups.append({"name": name, "profile_ids": []})
        self._persist_groups()

    def rename_group(self, old_name: str, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name or (new_name != old_name and new_name in self.groups):
            raise ValueError("分组名称不能为空且不能重复")
        for group in self._groups:
            if group.get("name") == old_name:
                group["name"] = new_name
                for profile in self._profiles:
                    if profile.group == old_name:
                        profile.group = new_name
                self._persist_groups()
                return
        raise ValueError("分组不存在")

    def remove_group(self, name: str) -> None:
        before = len(self._groups)
        self._groups = [group for group in self._groups if group.get("name") != name]
        if len(self._groups) == before:
            raise ValueError("分组不存在")
        for profile in self._profiles:
            if profile.group == name:
                profile.group = None
        self._persist_groups()

    def move_to_group(self, profile_id: str, group_name: str | None) -> None:
        if group_name is not None and group_name not in self.groups:
            raise ValueError("分组不存在")
        profile = self.get(profile_id)
        if profile is None:
            raise ValueError("连接不存在")
        for group in self._groups:
            ids = group.get("profile_ids", [])
            if isinstance(ids, list):
                group["profile_ids"] = [pid for pid in ids if str(pid) != profile_id]
        if group_name is not None:
            target = next(group for group in self._groups if group.get("name") == group_name)
            ids = target.setdefault("profile_ids", [])
            assert isinstance(ids, list)
            ids.append(profile_id)
        profile.group = group_name
        self._persist_groups()

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
        if profile.provider_key != "GaussDB":
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
