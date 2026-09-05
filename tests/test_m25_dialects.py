"""M25 测试：方言注册表与 URL/标识符构造（无服务器依赖）。"""

from __future__ import annotations

from magiccat.services import dialects


def test_providers_registry():
    assert dialects.supported_keys() == ["mysql", "mariadb", "postgresql", "gaussdb"]
    assert "postgresql" not in dialects.planned_keys()
    assert dialects.provider("postgresql").standard_metadata is True
    assert dialects.provider("gaussdb").standard_metadata is True
    assert dialects.provider("gaussdb").requires_external_driver is True
    assert dialects.provider("mysql").standard_metadata is False
    # 未知 key 回退默认
    assert dialects.provider("nope").key == "mysql"


def test_jdbc_url_shapes():
    assert dialects.build_jdbc_url("mysql", "127.0.0.1", 3306,
                                   "test") == "jdbc:mysql://127.0.0.1:3306/test"
    assert dialects.build_jdbc_url("postgresql", "10.0.0.1", 5432,
                                   "app") == "jdbc:postgresql://10.0.0.1:5432/app"
    assert dialects.build_jdbc_url("gaussdb", "10.0.0.1", 5432,
                                   "app") == "jdbc:gaussdb://10.0.0.1:5432/app"
    assert dialects.build_jdbc_url("sqlserver", "srv", 1433,
                                   "db") == "jdbc:sqlserver://srv:1433;databaseName=db"


def test_quote_ident():
    assert dialects.quote_ident("mysql", "t1") == "`t1`"
    assert dialects.quote_ident("postgresql", "Order") == '"Order"'
    assert dialects.quote_ident("gaussdb", "Order") == '"Order"'
    assert dialects.quote_ident("mysql", "a`b") == "`a``b`"
