"""按连接拆分的跨平台配置存储。

每个连接使用独立的 ``<provider_key>/Servers/<连接名称>/connection.json`` 文件，
组关系使用根目录下独立的 ``groups.json``。写入采用临时文件 + 原子替换；密码
按用户要求直接保存为 ``password`` 字段。这里不读取 Windows 注册表或任何旧版
聚合 JSON。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.services.dialects import PROVIDERS
from magiccat.storage import home_dir

logger = logging.getLogger(__name__)

_FORMAT_VERSION = 1


class JsonProfileStore:
    """按连接拆分的配置实现；旧的大文件格式不再读取。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else home_dir()
        self.groups_path = self.root / "groups.json"
        self._lock = threading.RLock()

    @classmethod
    def default(cls) -> JsonProfileStore:
        return cls()

    @property
    def path(self) -> Path:
        return self.root

    @property
    def connections_dir(self) -> Path:
        """返回连接产品目录的根路径（不再附加 ``connections`` 层）。"""
        return self.root

    @property
    def config_path(self) -> Path:
        return self.root

    @staticmethod
    def _safe_stem(name: str) -> str:
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
        stem = stem or "未命名连接"
        # Windows 保留设备名即使带扩展名也不能作为普通文件创建。
        if stem.split(".", 1)[0].upper() in {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            stem += "_"
        return stem

    @staticmethod
    def _safe_provider_dir(provider_key: str) -> str:
        """返回官方产品目录名，不改写产品名称中的空格。"""
        normalized = provider_key.strip()
        if normalized not in PROVIDERS:
            raise ValueError(f"不支持的数据库产品名称：{provider_key}")
        return normalized

    def _profile_dir(self, provider_key: str) -> Path:
        return self.root / self._safe_provider_dir(provider_key) / "Servers"

    def _iter_profile_paths(self):
        if not self.root.is_dir():
            return
        for provider_key in PROVIDERS:
            servers_dir = self.root / provider_key / "Servers"
            if servers_dir.is_dir():
                yield from servers_dir.glob("*/connection.json")

    def _find_profile_path(self, profile_id: str) -> Path | None:
        for path in self._iter_profile_paths() or ():
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(document, dict) and str(document.get("id", "")) == profile_id:
                return path
        return None

    def profile_path(self, profile_id: str) -> Path:
        """返回已保存连接的实际文件路径。"""
        found = self._find_profile_path(profile_id)
        if found is None:
            raise FileNotFoundError(f"连接配置不存在：{profile_id}")
        return found

    def _path_for_name(self, name: str, provider_key: str) -> Path:
        stem = self._safe_stem(name)
        return self._profile_dir(provider_key) / stem / "connection.json"

    def load(self) -> list[ConnectionProfile]:
        with self._lock:
            if not self.root.is_dir():
                return []
            profiles: list[ConnectionProfile] = []
            paths = sorted(self._iter_profile_paths() or (),
                           key=lambda p: (p.parent.name, p.name))
            for path in paths:
                try:
                    document = json.loads(path.read_text(encoding="utf-8"))
                    profile = self._decode(document)
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    logger.warning("读取连接配置失败 [%s]: %s", path, exc)
                    continue
                if profile is not None:
                    profiles.append(profile)
            return profiles

    @staticmethod
    def _decode(document: object) -> ConnectionProfile | None:
        if not isinstance(document, dict) or document.get("version") != _FORMAT_VERSION:
            logger.warning("忽略不受支持的连接配置文件")
            return None
        try:
            password = document.get("password", "")
            if not isinstance(password, str):
                raise TypeError("password 必须是字符串")
            provider_key = document.get("provider_key")
            if not isinstance(provider_key, str) or provider_key not in PROVIDERS:
                raise ValueError(f"不支持的数据库产品名称：{provider_key}")
            return ConnectionProfile.from_dict(document, password=password)
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            logger.warning("忽略无效连接配置项: %s", exc)
            return None

    def save_profile(self, profile: ConnectionProfile) -> None:
        document = {"version": _FORMAT_VERSION, **self._encode(profile)}
        with self._lock:
            current = self._find_profile_path(profile.id)
            target = self._path_for_name(profile.name, profile.provider_key)
            if target.exists() and target != current:
                raise ValueError(f"连接配置文件已存在，连接名称不可映射为同一文件：{profile.name}")
            self._atomic_write(target, document)
            if current is not None and current != target:
                try:
                    current.unlink()
                except FileNotFoundError:
                    pass
                self._remove_empty_connection_dir(current.parent)

    def delete_profile(self, profile_id: str) -> None:
        with self._lock:
            path = self._find_profile_path(profile_id)
            if path is None:
                return
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            self._remove_empty_connection_dir(path.parent)

    @staticmethod
    def _remove_empty_connection_dir(path: Path) -> None:
        """重命名/删除后仅清理连接自身的空目录。"""
        try:
            path.rmdir()
        except OSError:
            pass

    def load_groups(self) -> list[dict[str, object]]:
        with self._lock:
            try:
                document = json.loads(self.groups_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return []
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                logger.warning("读取连接分组失败 [%s]: %s", self.groups_path, exc)
                return []
            if not isinstance(document, dict) or document.get("version") != _FORMAT_VERSION:
                return []
            groups = document.get("groups")
            if not isinstance(groups, list):
                return []
            result: list[dict[str, object]] = []
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("name"), str):
                    continue
                ids = group.get("profile_ids", [])
                if not isinstance(ids, list):
                    ids = []
                result.append({"name": group["name"],
                               "profile_ids": [str(pid) for pid in ids]})
            return result

    def save_groups(self, groups: list[dict[str, object]]) -> None:
        self._atomic_write(self.groups_path, {"version": _FORMAT_VERSION,
                                              "groups": groups})

    def _atomic_write(self, path: Path, document: dict[str, object]) -> None:
        payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=path.parent,
                    prefix=f".{path.stem}.", suffix=".tmp", delete=False,
                ) as handle:
                    temporary = handle.name
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                temporary = None
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
            finally:
                if temporary:
                    try:
                        Path(temporary).unlink()
                    except OSError:
                        pass

    @staticmethod
    def _encode(profile: ConnectionProfile) -> dict[str, object]:
        entry = profile.to_dict()
        entry["password"] = profile.password
        return entry
