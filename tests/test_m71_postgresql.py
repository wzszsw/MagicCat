"""M71 测试：PostgreSQL 扩展（连接打开/自检 + 标准 JDBC 元数据）。需本机 PG 可达。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_pg_connection_and_metadata(qtbot, pg_env, connection_service):
    from magiccat.services.metadata_service import MetadataService

    profile = ConnectionProfile(name="PG1", group=DEFAULT_GROUP,
                                host=pg_env["host"], port=pg_env["port"],
                                username=pg_env["user"], password=pg_env["password"],
                                provider_key="PostgreSQL")
    connection_service.add(profile)

    # 打开连接并自检：返回 PostgreSQL 版本
    version = connection_service.open(profile)
    assert "PostgreSQL" in version

    meta = MetadataService(connection_service)
    # standard DatabaseMetaData 路径：databases 应含 postgres
    dbs = [d["name"] for d in meta.databases(profile)]
    assert "postgres" in dbs
    # 当前 schema 的表/视图（经 JDBC getTables，catalog=null/schema=名字）
    tables = meta.tables(profile, "public")
    assert isinstance(tables, list) and all(
        t.get("type") in ("BASE TABLE", "VIEW") for t in tables)

    connection_service.close(profile.id)


def test_pg_provider_supported():
    from magiccat.services import dialects

    assert dialects.provider("PostgreSQL").state == "supported"
    assert dialects.build_jdbc_url(
        "PostgreSQL", "127.0.0.1", 5432, "app"
    ) == "jdbc:postgresql://127.0.0.1:5432/app"
