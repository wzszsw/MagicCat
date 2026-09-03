"""应用设置（JSON 持久化于 MAGICCAT_HOME/settings.json）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULTS = {"theme": "light"}


class AppSettings:
    def __init__(self, root: Path) -> None:
        self.file = root / "settings.json"
        self._data: dict = {}
        self.load()

    @classmethod
    def default(cls) -> AppSettings:
        from magiccat.services.profile_store import _default_root

        return cls(_default_root())

    def load(self) -> None:
        try:
            if self.file.exists():
                self._data = json.loads(self.file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("settings.json 读取失败，使用默认值: %s", exc)
            self._data = {}
        for key, value in DEFAULTS.items():
            self._data.setdefault(key, value)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.file)
        except OSError as exc:
            logger.warning("settings 写入失败: %s", exc)
