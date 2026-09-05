"""跨平台连接配置存储。

连接配置使用用户数据目录下的 ``connections.json``，格式是 MagicCat 自有的
版本化 JSON 文档。写入采用临时文件 + 原子替换，避免应用被中断时留下半个
配置文件；密码按用户要求直接保存为 ``password`` 字段。

这里没有读取旧注册表或旧 JSON 文件的逻辑。存储格式是一次性的新格式，后续
格式变化应通过版本号显式升级，而不是隐式兼容历史数据。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.storage import home_dir

logger = logging.getLogger(__name__)

_FORMAT_VERSION = 1


class JsonProfileStore:
    """将连接配置持久化到用户数据目录中的 JSON 文件。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else home_dir()
        self.path = self.root / "connections.json"
        self._lock = threading.RLock()

    @classmethod
    def default(cls) -> JsonProfileStore:
        return cls()

    def load(self) -> list[ConnectionProfile]:
        with self._lock:
            try:
                raw = self.path.read_text(encoding="utf-8")
                document = json.loads(raw)
            except FileNotFoundError:
                return []
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                logger.warning("读取连接配置失败 [%s]: %s", self.path, exc)
                return []

            if not isinstance(document, dict) or document.get("version") != _FORMAT_VERSION:
                logger.warning("连接配置格式不受支持 [%s]", self.path)
                return []
            entries = document.get("connections")
            if not isinstance(entries, list):
                logger.warning("连接配置缺少 connections 数组 [%s]", self.path)
                return []

            profiles: list[ConnectionProfile] = []
            for entry in entries:
                profile = self._decode(entry)
                if profile is not None:
                    profiles.append(profile)
            return profiles

    @staticmethod
    def _decode(entry: object) -> ConnectionProfile | None:
        if not isinstance(entry, dict):
            logger.warning("忽略非法连接配置项")
            return None
        try:
            password = entry.get("password", "")
            if not isinstance(password, str):
                raise TypeError("password 必须是字符串")
            return ConnectionProfile.from_dict(entry, password=password)
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            logger.warning("忽略无效连接配置项: %s", exc)
            return None

    def save(self, profiles: list[ConnectionProfile]) -> None:
        document = {
            "version": _FORMAT_VERSION,
            "connections": [self._encode(profile) for profile in profiles],
        }
        payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.root,
                    prefix=".connections.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temporary = handle.name
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                temporary = None
                # User data may contain credentials; keep it private on Unix.
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
            except OSError as exc:
                logger.warning("保存连接配置失败 [%s]: %s", self.path, exc)
                raise
            finally:
                if temporary:
                    try:
                        Path(temporary).unlink()
                    except OSError:
                        pass

    @staticmethod
    def _encode(profile: ConnectionProfile) -> dict:
        entry = profile.to_dict()
        entry["password"] = profile.password
        return entry
