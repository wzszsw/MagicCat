"""M82 测试：PostgreSQL 表数据（page/columns/primary_key/update/insert/delete）
—— 验证标识符按方言转义（双引号而非 MySQL 反引号）、LIMIT/OFFSET 语法、主键查询。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def _profile(pg_env, name="M82pg"):
    return ConnectionProfile(name=name, host=pg_env["host"], port=pg_env["port"],
                             username=pg_env["user"], password=pg_env["password"],
                             provider_key="postgresql")


def test_pg_table_data_crud(qtbot, pg_env, connection_service):
    from magiccat.services.data_service import DataService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService

    profile = _profile(pg_env)
    connection_service.add(profile)
    connection_service.open(profile)
    q = QueryService(connection_service)
    meta = MetadataService(connection_service)
    data = DataService(connection_service)

    q.execute(profile, 'DROP TABLE IF EXISTS "public"."mc_pg_t"')
    q.execute(profile, 'CREATE TABLE "public"."mc_pg_t" (id bigint PRIMARY KEY, name varchar(50))')
    for i in (1, 2, 3):
        q.execute(profile, f'INSERT INTO "public"."mc_pg_t" (id, name) VALUES ({i}, \'row{i}\')')

    # 列元数据（标准 JDBC API）
    cols = meta.columns(profile, "public", "mc_pg_t")
    assert cols and cols[0]["name"] == "id"
    assert cols[0]["key"] == "PRI", f"id 应标记为主键: {cols[0]}"
    assert cols[1]["name"] == "name"

    # 主键
    pk = data.primary_key(profile, "public", "mc_pg_t")
    assert pk == ["id"]

    # 分页（含 LIMIT/OFFSET 语法）
    page1 = data.load_page(profile, "public", "mc_pg_t", offset=0, limit=2)
    assert page1["total"] == 3
    assert [r[0] for r in page1["rows"]] == ["1", "2"]

    # 更新 / 插入 / 删除
    assert data.update_row(profile, "public", "mc_pg_t", ["id"], ["1"], ["name"], ["edited"]) == 1
    assert data.insert_row(profile, "public", "mc_pg_t", ["id", "name"], ["4", "row4"]) == 1
    page = data.load_page(profile, "public", "mc_pg_t", offset=0, limit=10)
    names = {r[0]: r[1] for r in page["rows"]}
    assert names["1"] == "edited"
    assert names["4"] == "row4"
    assert data.delete_row(profile, "public", "mc_pg_t", ["id"], ["4"]) == 1

    q.execute(profile, 'DROP TABLE IF EXISTS "public"."mc_pg_t"')
    connection_service.close(profile.id)
