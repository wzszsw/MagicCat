"""M81 测试：连接编辑向导（产品选择页 → 表单页，产品默认值正确，编辑锁定产品）。

- 新建：第1页产品网格（MySQL/MariaDB/PostgreSQL/GaussDB，不含 Oracle/SQL Server）；
- 选 PG → 表单页默认 localhost/5432/postgres；切 MySQL → localhost/3306/root；
- 编辑：直接落表单页，产品类型锁定，保留原主机/端口。
"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def test_wizard_product_page_and_defaults(qtbot):
    from magiccat.ui.dialogs import ConnectionEditDialog

    d = ConnectionEditDialog(groups=["默认分组"])
    qtbot.addWidget(d)
    # 新建：落在产品页
    assert d._stack.currentWidget() is d._product_page
    assert sorted(d._cards.keys()) == ["gaussdb", "mariadb", "mysql", "postgresql"]
    assert "oracle" not in d._cards, "Oracle 不应出现在可选产品"

    d._select_product("postgresql")
    assert d._stack.currentWidget() is d._form_page
    assert d._form_title.text() == "PostgreSQL 连接"
    assert d.host_edit.text() in ("127.0.0.1", "localhost")
    assert d.port_spin.value() == 5432
    assert d.user_edit.text() == "postgres"
    assert d.db_edit.text() == "postgres"

    d.type_combo.setCurrentIndex(d.type_combo.findData("mysql"))
    assert d._form_title.text() == "MySQL 连接"
    assert d.port_spin.value() == 3306
    assert d.user_edit.text() == "root"

    d.type_combo.setCurrentIndex(d.type_combo.findData("gaussdb"))
    assert d._form_title.text() == "GaussDB 连接"
    assert d.port_spin.value() == 5432
    assert d.user_edit.text() == "gaussdb"
    assert d.db_edit.text() == "postgres"


def test_wizard_edit_locks_product_and_preserves(qtbot):
    from magiccat.ui.dialogs import ConnectionEditDialog

    p = ConnectionProfile(name="MyPG", group=DEFAULT_GROUP, host="10.0.0.1", port=5432,
                          username="postgres", password="x", provider_key="postgresql")
    d = ConnectionEditDialog(profile=p, groups=["默认分组"])
    qtbot.addWidget(d)
    # 编辑：直接落表单页
    assert d._stack.currentWidget() is d._form_page
    # 产品类型锁定
    assert not d.type_combo.isEnabled()
    # 保留原值
    assert d.host_edit.text() == "10.0.0.1"
    assert d.port_spin.value() == 5432
    assert d.type_combo.currentData() == "postgresql"


def test_wizard_profile_roundtrip(qtbot):
    from magiccat.ui.dialogs import ConnectionEditDialog

    d = ConnectionEditDialog(groups=["默认分组"])
    qtbot.addWidget(d)
    d._select_product("postgresql")
    d.name_edit.setText("p1")
    prof = d.profile()
    assert prof.provider_key == "postgresql"
    assert prof.port == 5432
    assert prof.username == "postgres"
    assert prof.group == DEFAULT_GROUP
