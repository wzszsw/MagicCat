"""M20 测试：计划任务（存储/到期判断/备份执行）。"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services.tasks import Task, TaskLock, TaskStore, _due, run_backup_task


def test_task_store_and_due(tmp_path):
    store = TaskStore(tmp_path)
    assert store.load() == []
    task = Task(name="夜备", kind="backup", profile_id="p1", schema="app",
                interval_min=60, target_dir=str(tmp_path))
    store.save([task])
    reloaded = TaskStore(tmp_path).load()
    assert reloaded[0].name == "夜备" and reloaded[0].schema == "app"

    # 到期逻辑：未运行 → 到期；刚运行 → 未到期；停用 → 永不
    assert _due(reloaded[0], time.time())
    reloaded[0].last_run = datetime.now(UTC).isoformat(timespec="seconds")
    assert not _due(reloaded[0], time.time())
    reloaded[0].enabled = False
    reloaded[0].last_run = ""
    assert not _due(reloaded[0], time.time())


def test_task_lock():
    lock = TaskLock()
    assert lock.try_acquire("a")
    assert not lock.try_acquire("a")
    lock.release("a")
    assert lock.try_acquire("a")


def test_task_submit_error_is_reported_before_dialog_accepts(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from magiccat.services.connection_service import ConnectionService
    from magiccat.services.profile_store import ProfileStore
    from magiccat.ui.task_dialog import _TaskEditDialog

    errors: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, _title, text, *args: errors.append(text)),
    )

    class EmptyMetadata:
        def databases(self, _profile):
            return []

    def submit(_task):
        raise OSError("任务配置保存失败")

    dialog = _TaskEditDialog(
        ConnectionService(ProfileStore(tmp_path)),
        EmptyMetadata(), submit_callback=submit)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("夜备")
    dialog.dir_edit.setText("backups")
    dialog._accept()

    assert dialog.result() == 0
    assert errors == ["任务配置保存失败"]


def test_run_backup_task(mysql_env, connection_service, tmp_path):
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M20", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    db = f"mc_m20_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE DATABASE `{db}`")
        q.execute(profile, (
            f"CREATE TABLE `{db}`.`t` (id INT PRIMARY KEY, v VARCHAR(20))"))
        q.execute(profile, f"INSERT INTO `{db}`.`t` VALUES (1, '任务')")

        task = Task(name="自动备份", kind="backup", profile_id=profile.id,
                    schema=db, interval_min=60, target_dir=str(tmp_path))
        status = run_backup_task(task, profile, connection_service)
        assert "OK" in status and "表1" in status
        files = list(tmp_path.glob("backup_*.sql"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert f"MagicCat 全库备份 · {db}" in text
    finally:
        q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
        connection_service.close(profile.id)
