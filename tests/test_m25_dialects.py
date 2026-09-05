"""M25 测试：方言注册表与 URL/标识符构造（无服务器依赖）。"""

from __future__ import annotations

from magiccat.services import dialects


def test_providers_registry():
    assert dialects.supported_keys() == ["MySQL", "MariaDB", "PostgreSQL", "GaussDB"]
    assert "PostgreSQL" not in dialects.planned_keys()
    assert dialects.provider("PostgreSQL").standard_metadata is True
    assert dialects.provider("GaussDB").standard_metadata is True
    assert dialects.provider("GaussDB").requires_external_driver is True
    assert dialects.provider("MySQL").standard_metadata is False
    # 未知 key 回退默认
    assert dialects.provider("nope").key == "MySQL"


def test_jdbc_url_shapes():
    assert dialects.build_jdbc_url("MySQL", "127.0.0.1", 3306,
                                   "test") == "jdbc:mysql://127.0.0.1:3306/test"
    assert dialects.build_jdbc_url("PostgreSQL", "10.0.0.1", 5432,
                                   "app") == "jdbc:postgresql://10.0.0.1:5432/app"
    assert dialects.build_jdbc_url("GaussDB", "10.0.0.1", 5432,
                                   "app") == "jdbc:gaussdb://10.0.0.1:5432/app"
    assert dialects.build_jdbc_url("SQL Server", "srv", 1433,
                                   "db") == "jdbc:sqlserver://srv:1433;databaseName=db"


def test_quote_ident():
    assert dialects.quote_ident("MySQL", "t1") == "`t1`"
    assert dialects.quote_ident("PostgreSQL", "Order") == '"Order"'
    assert dialects.quote_ident("GaussDB", "Order") == '"Order"'
    assert dialects.quote_ident("MySQL", "a`b") == "`a``b`"
