"""M80 测试：数据库产品连接图标按 provider_key 区分（非空且互异），未知回退通用。"""

from __future__ import annotations


def test_product_connection_icons(qtbot):
    from magiccat.ui.icons import icon

    keys = ["MySQL", "PostgreSQL", "MariaDB", "Oracle", "SQL Server"]
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
                          provider_key="PostgreSQL")
    connection_service.add(p)
    ex = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(ex)
    ex.load_profiles()

    node_icon = ex.profile_item(p.id).icon(0)
    from magiccat.ui.icons import closed_profile_icon
    assert node_icon.cacheKey() == closed_profile_icon("PostgreSQL").cacheKey(), \
        "关闭的 PG 连接节点应使用 PostgreSQL 的灰度图标"
    assert node_icon.cacheKey() != closed_profile_icon("MySQL").cacheKey(), \
        "关闭的 PG 节点图标不应与 MySQL 相同"
    connection_service.close(p.id)


def test_closed_profile_icon_only_affects_explorer_nodes(qtbot, connection_service, monkeypatch):
    from PySide6.QtWidgets import QComboBox

    from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.icons import closed_profile_icon, icon
    from magiccat.ui.object_explorer import ObjectExplorer
    from magiccat.ui.profile_combo import add_profile_item

    mysql = ConnectionProfile(name="MySQL", group=DEFAULT_GROUP, host="1.2.3.4", port=3306,
                              provider_key="MySQL")
    postgres = ConnectionProfile(name="PostgreSQL", group=DEFAULT_GROUP, host="1.2.3.5", port=5432,
                                 provider_key="PostgreSQL")
    connection_service.add(mysql)
    connection_service.add(postgres)
    explorer = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(explorer)
    explorer.load_profiles()

    mysql_item = explorer.profile_item(mysql.id)
    postgres_item = explorer.profile_item(postgres.id)
    assert mysql_item is not None
    assert postgres_item is not None
    # 启动时 JDBC 连接均未打开，树中全部为关闭态灰度图标。
    assert mysql_item.icon(0).cacheKey() == closed_profile_icon("MySQL").cacheKey()
    assert postgres_item.icon(0).cacheKey() == closed_profile_icon("PostgreSQL").cacheKey()

    # 左树选中不改变连接打开状态或图标。
    explorer.setCurrentItem(mysql_item)
    assert mysql_item.icon(0).cacheKey() == closed_profile_icon("MySQL").cacheKey()

    monkeypatch.setattr(connection_service, "is_open", lambda profile_id: profile_id == mysql.id)
    explorer._set_profile_icon(mysql_item)
    explorer._set_profile_icon(postgres_item)
    assert mysql_item.icon(0).cacheKey() == icon("profile", "MySQL").cacheKey()
    assert postgres_item.icon(0).cacheKey() == closed_profile_icon("PostgreSQL").cacheKey()

    # 查询等连接下拉仍始终使用彩色产品图标，树状态不外溢。
    combo = QComboBox()
    qtbot.addWidget(combo)
    add_profile_item(combo, mysql)
    assert combo.itemIcon(0).cacheKey() == icon("profile", "MySQL").cacheKey()


def test_profile_context_menu_lists_open_close_first(qtbot, connection_service, monkeypatch):
    from PySide6.QtWidgets import QMenu

    from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer

    profile = ConnectionProfile(name="MySQL", group=DEFAULT_GROUP, host="1.2.3.4", port=3306)
    connection_service.add(profile)
    explorer = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(explorer)
    explorer.load_profiles()
    item = explorer.profile_item(profile.id)
    assert item is not None
    closed_menu = QMenu(explorer)
    explorer._add_profile_menu_items(closed_menu, profile)
    assert [action.text() for action in closed_menu.actions()][:3] == ["打开连接", "测试连接", "刷新"]

    monkeypatch.setattr(connection_service, "is_open", lambda _profile_id: True)
    opened_menu = QMenu(explorer)
    explorer._add_profile_menu_items(opened_menu, profile)
    assert [action.text() for action in opened_menu.actions()][:3] == ["关闭连接", "测试连接", "刷新"]
