"""M12 测试：表设计器“新建表”模式 + 对象 DDL 生成。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_designer_new_table_flow(qtbot, mysql_env, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService
    from magiccat.ui.table_designer import TableDesignerDialog

    profile = ConnectionProfile(name="M12", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    meta = MetadataService(connection_service)
    table = f"mc_m12_new_{int(time.time() * 1000)}"
    try:
        dialog = TableDesignerDialog(profile, "test", table, connection_service,
                                     new_table=True)
        qtbot.addWidget(dialog)
        assert dialog.new_table and dialog.columns_grid.rowCount() >= 1

        # 填写主键列 id
        grid = dialog.columns_grid
        r0 = 0
        grid.item(r0, 0).setText("id")
        grid.item(r0, 1).setText("int")
        grid.item(r0, 2).setText("NO")
        base = dict(grid.item(r0, 0).data(0x0100))
        base["key"] = "PRI"
        base["extra"] = "auto_increment"
        grid.item(r0, 0).setData(0x0100, base)

        # 追加一列 name
        dialog._add_column_row()
        r1 = 1
        grid.item(r1, 0).setText("name")
        grid.item(r1, 1).setText("varchar(50)")
        grid.item(r1, 2).setText("YES")
        grid.item(r1, 3).setText("'佚名'")

        dialog._generate_preview()
        preview = dialog.sql_preview.toPlainText()
        assert "CREATE TABLE" in preview
        assert "PRIMARY KEY (`id`)" in preview
        assert "AUTO_INCREMENT" in preview
        assert "DEFAULT '佚名'" in preview

        # 取生成的 SQL 直接执行（弹确认框的 _apply 不在测试内触发）
        sql = dialog._build_sql(dialog._read_columns())
        assert sql is not None and sql.startswith("CREATE TABLE")
        results = q.execute(profile, sql)
        assert all(r["kind"] == "update" for r in results)

        cols = meta.columns(profile, "test", table)
        names = [c["name"] for c in cols]
        assert names == ["id", "name"]
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `test`.`{table}`")
        connection_service.close(profile.id)
