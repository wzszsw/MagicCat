"""计划任务（M6b 轻量版）：应用运行期间按间隔自动执行备份任务。

- 任务定义 JSON 持久化（MAGICCAT_HOME/tasks.json）；
- 调度：MainWindow 内 QTimer 周期性调用 TasksScheduler.scan_due(now)，
  到期任务在后台线程执行（数据库访问不阻塞 UI）；
- 记录 last_run / last_status 便于 UI 展示。
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.data_service import DataService
from magiccat.services.ddl_service import DdlService
from magiccat.services.metadata_service import MetadataService

logger = logging.getLogger(__name__)

_BACKUP_NAME_RE = re.compile(r"[^0-9A-Za-z_.-]")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Task:
    name: str
    kind: str  # 目前仅 backup
    profile_id: str
    schema: str
    interval_min: int = 60
    target_dir: str = ""
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    last_run: str = ""     # ISO（UTC）
    last_status: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__})


class TaskStore:
    def __init__(self, root: Path) -> None:
        self.file = root / "tasks.json"

    @classmethod
    def default(cls) -> TaskStore:
        from magiccat.services.profile_store import _default_root

        return cls(_default_root())

    def load(self) -> list[Task]:
        import json

        if not self.file.exists():
            return []
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return [Task.from_dict(t) for t in data.get("tasks", []) if t.get("name")]
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning("tasks.json 读取失败: %s", exc)
            return []

    def save(self, tasks: list[Task]) -> None:
        import json

        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"tasks": [t.to_dict() for t in tasks]},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.file)
        except OSError as exc:
            logger.warning("tasks 写入失败: %s", exc)


def _due(task: Task, now: float | None = None) -> bool:
    """到期判断：从未运行或距上次运行 ≥ interval_min。"""
    if not task.enabled:
        return False
    now = time.time() if now is None else now
    if not task.last_run:
        return True
    try:
        last = datetime.fromisoformat(task.last_run).timestamp()
    except ValueError:
        return True
    return now - last >= task.interval_min * 60 - 1


def run_backup_task(task: Task, profile: ConnectionProfile, connections: ConnectionService,
                    target_dir: str | None = None) -> str:
    """执行一次备份任务，返回状态文本（或抛异常）。"""
    from magiccat.services import backup

    out_dir = Path(target_dir or task.target_dir or "backups")
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = _BACKUP_NAME_RE.sub("_", f"{task.schema}_{task.name}")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"backup_{safe}_{stamp}.sql"
    result = backup.dump_schema_sql(
        profile, task.schema, path,
        DataService(connections), MetadataService(connections), DdlService(connections))
    text = (f"OK 表{result['tables']}/视图{result['views']}/"
            f"函数+存储过程{result['routines']}/触发器{result['triggers']} · "
            f"{result['rows']} 行 → {path.name}")
    return text


def parse_due_status(task: Task) -> str:
    """仅展示用途。"""
    if task.last_run:
        return f"上次 {task.last_run} · {task.last_status or '-'}"
    return "未运行"


class TaskLock:
    """防重入：同一任务执行中不重复触发。"""

    def __init__(self) -> None:
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def try_acquire(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._running:
                return False
            self._running.add(task_id)
            return True

    def release(self, task_id: str) -> None:
        with self._lock:
            self._running.discard(task_id)
