"""M6 测试：主题设置、ER 图模型与对话框、SQL 备份/恢复。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services import backup
from magiccat.services.er_model import build_er_model


def _profile(mysql_env: dict) -> ConnectionProfile:
    return ConnectionProfile(name="M6", group=DEFAULT_GROUP, database="test",
                             host=mysql_env["host"], port=mysql_env["port"],
                             username=mysql_env["user"], password=mysql_env["password"])


# ---- 主题 ----
def test_settings_roundtrip(tmp_path):
    from magiccat.services.settings import AppSettings

    s = AppSettings(tmp_path)
    assert s.get("theme") == "light"
    s.set("theme", "dark")
    reloaded = AppSettings(tmp_path)
    assert reloaded.get("theme") == "dark"


def test_theme_toggle(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.settings import AppSettings
    from magiccat.ui.main_window import MainWindow

    settings = AppSettings(connection_service._store.root)
    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    assert win.styleSheet() == ""  # 默认浅色
    win._toggle_theme(True)
    assert "#2B2D30" in win.styleSheet()
    assert settings.get("theme") == "dark"
    win._toggle_theme(False)
    assert win.styleSheet() == ""


# ---- ER ----
def test_er_model_pure():
    tables = [{"name": "users"}, {"name": "orders"}]
    columns_of = {
        "users": [{"name": "id", "data_type": "int", "key": "PRI"},
                  {"name": "name", "data_type": "varchar(20)", "key": ""}],
        "orders": [{"name": "id", "data_type": "int", "key": "PRI"},
                   {"name": "user_id", "data_type": "int", "key": "MUL"}],
    }
    fk_rows_of = {
        "orders": [{"column_name": "user_id", "ref_table": "users",
                    "ref_column": "id", "constraint_name": "fk_user"}],
    }
    model = build_er_model("test", tables, columns_of, fk_rows_of)
    assert [t.name for t in model.tables] == ["users", "orders"]
    assert len(model.fks) == 1
    fk = model.fks[0]
    assert fk.child_table == "orders" and fk.parent_table == "users"
    assert fk.child_col == "user_id" and fk.parent_col == "id"
    # 指向模型外表的边应被过滤
    model2 = build_er_model("test", [{"name": "orders"}],
                            {"orders": columns_of["orders"]},
                            fk_rows_of)
    assert model2.fks == []


def test_er_dialog_loads(qtbot, tmp_path, mysql_env, connection_service):
    from magiccat.services.query_service import QueryService
    from magiccat.ui.er_view import ErDialog

    profile = _profile(mysql_env)
    connection_service.add(profile)
    q = QueryService(connection_service)
    db = f"mc_m6_er_{int(time.time() * 1000)}"
    try:
        q.execute(profile, f"CREATE DATABASE `{db}`")
        q.execute(profile, f"CREATE TABLE `{db}`.`users` (id INT PRIMARY KEY, name VARCHAR(20))")
        q.execute(profile, (
            f"CREATE TABLE `{db}`.`orders` (id INT PRIMARY KEY, user_id INT NOT NULL, "
            f"CONSTRAINT fk_u FOREIGN KEY (user_id) REFERENCES `{db}`.`users`(id))"))
        dialog = ErDialog(profile, db, connection_service)
        qtbot.addWidget(dialog)

        def loaded() -> bool:
            return "条外键关系" in dialog.status.text() or "加载失败" in dialog.status.text()

        qtbot.waitUntil(loaded, timeout=25_000)
        assert "2 张表" in dialog.status.text() and "1 条外键" in dialog.status.text()

        png = tmp_path / "er.png"
        dialog.view.export_png(str(png))
        assert png.exists() and png.stat().st_size > 100
    finally:
        q.execute(profile, f"DROP DATABASE IF EXISTS `{db}`")
        connection_service.close(profile.id)


# ---- 备份 / 恢复 ----
def test_backup_restore_roundtrip(tmp_path, mysql_env, connection_service):
    from magiccat.services.data_service import DataService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService

    profile = _profile(mysql_env)
    connection_service.add(profile)
    q = QueryService(connection_service)
    data = DataService(connection_service)
    meta = MetadataService(connection_service)
    suffix = int(time.time() * 1000)
    users = f"mc_m6b_users_{suffix}"
    orders = f"mc_m6b_orders_{suffix}"
    try:
        q.execute(profile, f"CREATE TABLE `{users}` (id INT PRIMARY KEY, name VARCHAR(20))")
        q.execute(profile, (
            f"CREATE TABLE `{orders}` (id INT PRIMARY KEY, user_id INT NOT NULL, "
            f"CONSTRAINT fk FOREIGN KEY (user_id) REFERENCES `{users}`(id))"))
        q.execute(profile, f"INSERT INTO `{users}` VALUES (1, '小李'), (2, '老王')")
        q.execute(profile, f"INSERT INTO `{orders}` VALUES (10, 1), (11, 2), (12, 2)")

        sql_path = tmp_path / "backup.sql"
        res = backup.dump_tables_sql(profile, "test", [users, orders], sql_path,
                                     data, meta)
        assert res["tables"] == 2 and res["rows"] == 5

        # 删表后整库回灌（文件含两个 CREATE）
        q.execute(profile, f"DROP TABLE IF EXISTS `{orders}`")
        q.execute(profile, f"DROP TABLE IF EXISTS `{users}`")
        restored = backup.restore_sql_file(profile, sql_path, q)
        assert restored["ok"], restored["errors"]

        rows = q.execute(profile, f"SELECT COUNT(*) FROM `{users}`")
        assert rows[0]["rows"] == [["2"]]
        rows = q.execute(profile, f"SELECT COUNT(*) FROM `{orders}`")
        assert rows[0]["rows"] == [["3"]]
        # 外键约束恢复后仍有效：插入悬空 user_id 应失败
        bad = q.execute(profile, f"INSERT INTO `{orders}` VALUES (99, 999)")
        assert bad[0]["kind"] == "error"
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{orders}`")
        q.execute(profile, f"DROP TABLE IF EXISTS `{users}`")
        connection_service.close(profile.id)
