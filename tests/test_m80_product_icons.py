"""M80 测试：数据库产品连接图标按 provider_key 区分（非空且互异），未知回退通用。"""

from __future__ import annotations


def test_product_connection_icons(qtbot):
    from magiccat.ui.icons import icon

    keys = ["mysql", "postgresql", "mariadb", "oracle", "sqlserver"]
    icons = {k: icon("profile", k) for k in keys}
    for k, ic in icons.items():
        assert not ic.isNull(), f"{k} 图标不应为空"
    # 互异
    cks = [icons[k].cacheKey() for k in keys]
    assert len(set(cks)) == len(cks), "各产品图标应互异"
    # 未知/空回退通用连接图标（非空）
    assert not icon("profile", "unknown").isNull()
    assert not icon("profile", "").isNull()


def test_profile_node_uses_provider_icon(qtbot, connection_service):
    from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer

    # 建一个 PG 连接，验证树里 profile 节点图标使用 PG 专属（非 MySQL 通用）
    p = ConnectionProfile(name="PGi", group=DEFAULT_GROUP, host="1.2.3.4", port=5432,
                          provider_key="postgresql")
    connection_service.add(p)
    ex = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(ex)
    ex.load_profiles()

    node_icon = ex.topLevelItem(0).child(0).icon(0)
    from magiccat.ui.icons import icon as _icon
    assert node_icon.cacheKey() == _icon("profile", "postgresql").cacheKey(), \
        "PG 连接节点应使用 PostgreSQL 专属图标"
    assert node_icon.cacheKey() != _icon("profile", "mysql").cacheKey(), \
        "PG 节点图标不应与 MySQL 相同"
    connection_service.close(p.id)
