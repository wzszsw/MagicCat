"""连接配置文件存储（profiles.json）。

- 存储位置：$MAGICCAT_HOME（未设置则 %APPDATA%\\MagicCat），开发测试可指向临时目录。
- 密码字段以 DPAPI 密文落盘，见 utils/dpapi.py。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.utils import dpapi

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1
_FILE_NAME = "profiles.json"


def _default_root() -> Path:
    override = os.environ.get("MAGICCAT_HOME")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "MagicCat"


class ProfileStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _default_root()
        self.file = self.root / _FILE_NAME

    @classmethod
    def default(cls) -> ProfileStore:
        return cls(_default_root())

    def load(self) -> list[ConnectionProfile]:
        if not self.file.exists():
            return []
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("profiles.json 读取失败，按空配置处理: %s", exc)
            return []
        profiles: list[ConnectionProfile] = []
        for item in raw.get("profiles", []):
            try:
                enc = item.get("password_enc", "")
                profiles.append(ConnectionProfile.from_dict(item, password=dpapi.decrypt_text(enc)))
            except (KeyError, ValueError) as exc:
                logger.warning("跳过损坏的连接配置 %s: %s", item.get("name", "<unknown>"), exc)
        return profiles

    def save(self, profiles: list[ConnectionProfile]) -> None:
        payload = {
            "version": CONFIG_VERSION,
            "profiles": [
                {**p.to_dict(), "password_enc": dpapi.encrypt_text(p.password)} for p in profiles
            ],
        }
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.file)
