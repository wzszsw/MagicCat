"""M15 测试：运行中查询取消（Statement.cancel → 服务端中断）。"""

from __future__ import annotations

import threading
import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_cancel_long_query(mysql_env, connection_service):
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M15", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    # 先在主线程打开，确保 JVM/连接就绪
    connection_service.open(profile)
    svc = QueryService(connection_service)
    holder: dict = {}
    started = time.perf_counter()

    def run() -> None:
        holder["res"] = svc.execute(profile, "SELECT SLEEP(30)")

    t = threading.Thread(target=run)
    t.start()

    # 等执行进入语句（worker attach + 连接）
    for _ in range(50):
        if svc.active_count() >= 1:
            break
        time.sleep(0.1)
    assert svc.active_count() == 1, "查询应处于活跃状态"
    time.sleep(0.3)  # 确保已真正提交执行

    cancelled = svc.cancel_all()
    assert cancelled >= 1
    t.join(timeout=10)
    elapsed = time.perf_counter() - started
    assert not t.is_alive(), "取消后查询线程应结束"
    assert elapsed < 10, f"取消应中断 SLEEP(30)，实际耗时 {elapsed:.1f}s"
    res = holder["res"]
    assert len(res) == 1
    connection_service.close(profile.id)


def test_no_cancel_baseline(mysql_env, connection_service):
    """对照：不取消时 SLEEP(2) 应完整执行约 2s。"""
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M15b", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    svc = QueryService(connection_service)
    t0 = time.perf_counter()
    res = svc.execute(profile, "SELECT SLEEP(2)")
    assert time.perf_counter() - t0 >= 1.8
    assert res[0]["kind"] == "query"
    connection_service.close(profile.id)
