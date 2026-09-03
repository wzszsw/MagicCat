"""M28 测试：DDL 生成保真（字符集/排序规则/ON UPDATE/关键字默认值）。"""

from __future__ import annotations

from magiccat.services.ddl_builder import build_create, column_def


def _col(**kw) -> dict:
    base = {"name": "c", "data_type": "varchar(50)", "nullable": "NO",
            "default_value": None, "extra": "", "key": "", "comment": ""}
    base.update(kw)
    return base


def test_column_def_keeps_charset_collation():
    sql = column_def(_col(charset="utf8mb4", collation="utf8mb4_unicode_ci"))
    assert "CHARACTER SET utf8mb4" in sql
    assert "COLLATE utf8mb4_unicode_ci" in sql
    # 无字符集时不应拼出空标签
    assert "CHARACTER SET" not in column_def(_col())


def test_timestamp_on_update_and_keyword_default():
    sql = column_def({
        "name": "updated_at", "data_type": "timestamp",
        "nullable": "YES", "default_value": "CURRENT_TIMESTAMP",
        "extra": "DEFAULT_GENERATED on update CURRENT_TIMESTAMP",
        "key": "", "comment": "更新时间",
    })
    assert "DEFAULT CURRENT_TIMESTAMP" in sql, sql          # 不被引号包裹
    assert "'CURRENT_TIMESTAMP'" not in sql
    assert "ON UPDATE CURRENT_TIMESTAMP" in sql
    assert "COMMENT '更新时间'" in sql


def test_build_create_full_fidelity():
    cols = [
        {"name": "id", "data_type": "bigint unsigned", "nullable": "NO",
         "default_value": None, "extra": "auto_increment", "key": "PRI",
         "comment": "", "charset": "", "collation": ""},
        {"name": "name", "data_type": "varchar(30)", "nullable": "NO",
         "default_value": "佚名", "extra": "", "key": "",
         "comment": "", "charset": "utf8mb4", "collation": "utf8mb4_general_ci"},
        {"name": "updated_at", "data_type": "datetime", "nullable": "YES",
         "default_value": "CURRENT_TIMESTAMP",
         "extra": "DEFAULT_GENERATED on update CURRENT_TIMESTAMP", "key": "",
         "comment": "", "charset": "", "collation": ""},
    ]
    sql = build_create("app", "t_log", cols)
    assert "PRIMARY KEY (`id`)" in sql
    assert "AUTO_INCREMENT" in sql
    assert "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci" in sql
    assert "DEFAULT '佚名'" in sql
    assert "DEFAULT CURRENT_TIMESTAMP" in sql and "ON UPDATE CURRENT_TIMESTAMP" in sql
