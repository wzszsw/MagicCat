"""M13 测试：结果网格导出 CSV / 表导出跟随筛选。"""

from __future__ import annotations

import csv
import time


def test_result_view_export_csv(tmp_path, qtbot):
    from magiccat.ui.grid import ResultTableModel, ResultView

    model = ResultTableModel(["id", "name", "note"],
                             [["1", "奥力给", None], ["2", "中文,带逗号", "x"]])
    view = ResultView()
    qtbot.addWidget(view)
    view.setModel(model)
    path = tmp_path / "result.csv"
    count = view.export_csv(path)
    assert count == 2
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["id", "name", "note"]
    assert rows[1] == ["1", "奥力给", ""]        # None → 空串
    assert rows[2] == ["2", "中文,带逗号", "x"]   # 含逗号按 CSV 规范保留


def test_export_table_respects_where(tmp_path, mysql_env, connection_service):
    from magiccat.services import transfer
    from magiccat.services.data_service import DataService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfileWrapper(mysql_env)
    connection_service.add(profile)
    q = QueryService(connection_service)
    data = DataService(connection_service)
    meta = MetadataService(connection_service)
    table = f"mc_m13_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE TABLE `{table}` (id INT PRIMARY KEY, v VARCHAR(20))")
        q.execute(profile, f"INSERT INTO `{table}` VALUES (1,'a'),(2,'b'),(3,'c')")
        path = tmp_path / "filtered.csv"
        res = transfer.export_table(profile, "test", table, path, "csv", data, meta,
                                    where="id > 1")
        assert res["rows"] == 2
        with open(path, encoding="utf-8-sig", newline="") as f:
            body = [r for r in csv.reader(f)][1:]
        assert [r[0] for r in body] == ["2", "3"]
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{table}`")
        connection_service.close(profile.id)


def ConnectionProfileWrapper(mysql_env: dict):
    from magiccat.models.profile import ConnectionProfile

    return ConnectionProfile(name="M13", group="默认分组", database="test",
                             host=mysql_env["host"], port=mysql_env["port"],
                             username=mysql_env["user"], password=mysql_env["password"])
