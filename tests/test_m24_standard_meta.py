"""M24 测试：元数据实现按数据库产品选择（MySQL 走富信息层，作用域正确）。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_mysql_metadata_scoped_and_selection(mysql_env, connection_service):
    """MySQL 下对象清单来自 information_schema（作用域精确），标准实现用于其它库。"""
    from magiccat.services.metadata_service import MetadataService

    profile = ConnectionProfile(name="M24", group=DEFAULT_GROUP,
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    meta = MetadataService(connection_service)

    dbs = {d["name"] for d in meta.databases(profile)}
    assert {"mysql", "information_schema", "sys"}.issubset(dbs)

    tables = meta.tables(profile, "mysql")
    names = [t["name"] for t in tables]
    assert "user" in names, "mysql 库应含系统表 user（作用域须为 mysql 而非全服务器）"
    assert "books" not in names, "不应混入其它库的表（MySQL 走 information_schema 精确作用域）"
    # information_schema 中的系统“库级表”归属 mysql 库
    assert all(t["type"] in ("BASE TABLE", "VIEW") for t in tables)

    cols = meta.columns(profile, "mysql", "user")
    assert cols and any(c["name"] == "Host" for c in cols)
    connection_service.close(profile.id)
