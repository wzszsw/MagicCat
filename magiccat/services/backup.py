"""SQL 备份 / 恢复（M6 轻量版）。

备份 = 选定数据库（或表子集）→ 单个 .sql 文件（逐表 CREATE + 分块 INSERT）；
恢复 = 直接执行 .sql 脚本（语句级拆分，错误收集上报）。
本实现不调用 mysqldump 外部程序，全部走 JDBC（与导出链路同源）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.services.data_service import DataService
from magiccat.services.ddl_builder import build_create, group_foreign_keys, group_indexes
from magiccat.services.metadata_service import MetadataService
from magiccat.services.query_service import QueryService
from magiccat.services.transfer import _check, _qname, _sql_string

ProgressCb = Callable[[int, int, str], None]


def dump_tables_sql(profile: ConnectionProfile, schema: str, tables: list[str],
                    path: str | Path, data: DataService, metadata: MetadataService,
                    progress: ProgressCb | None = None,
                    cancel: threading.Event | None = None) -> dict:
    """备份若干表（结构 + 数据）为一个 .sql。返回 {tables, rows, cancelled}。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    total_rows = 0
    done_tables = 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"-- MagicCat 备份 · {schema} · {len(tables)} 张表\n\n")
        for table in tables:
            _check(cancel)
            columns = metadata.columns(profile, schema, table)
            if not columns:
                continue  # 视图/无权限对象跳过
            nullable = {c["name"]: c.get("nullable") == "YES" for c in columns}
            indexes = group_indexes(metadata.indexes(profile, schema, table))
            fks = group_foreign_keys(metadata.foreign_keys(profile, schema, table))
            f.write(f"-- 表 {table}\n")
            f.write(build_create(schema, table, columns, indexes, fks) + ";\n")
            qtable = _qname(schema, table)
            headers = [c["name"] for c in columns]

            offset = 0
            while True:
                _check(cancel)
                page = data.load_page(profile, schema, table, offset=offset, limit=1000)
                rows = page["rows"]
                for row in rows:
                    values = []
                    for name, v in zip(headers, row):
                        if v is None or v == "" and nullable.get(name, False):
                            values.append("NULL")
                        else:
                            values.append(_sql_string(v))
                    f.write(f"INSERT INTO {qtable} VALUES ({', '.join(values)});\n")
                total_rows += len(rows)
                if len(rows) < 1000:
                    break
                offset += 1000
            done_tables += 1
            if progress:
                progress(done_tables, len(tables), f"已备份 {done_tables}/{len(tables)} 张表")
    if progress:
        progress(done_tables, len(tables), f"完成：{total_rows} 行")
    return {"tables": done_tables, "rows": total_rows, "cancelled": False}


def _routine_block(body: str, kind: str, schema: str, name: str) -> str:
    """把含内部 ';' 的例程/触发器定义包装为可被语句切分器识别的块：
    DELIMITER $$ … $$，并在前补 DROP IF EXISTS 便于幂等恢复。"""
    text = body.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return (f"DROP {kind} IF EXISTS `{schema}`.`{name}`;\n"
            f"DELIMITER $$\n{text}\n$$\nDELIMITER ;\n")


def dump_schema_sql(profile: ConnectionProfile, schema: str, path: str | Path,
                    data: DataService, metadata: MetadataService,
                    ddl,  # DdlService
                    progress: ProgressCb | None = None,
                    cancel: threading.Event | None = None,
                    with_data: bool = True) -> dict:
    """全库备份：基础表(结构+数据，with_data=False 时仅结构) + 视图 + 例程 + 触发器。

    返回 {tables, rows, views, routines, triggers, cancelled}。
    """
    from magiccat.services.ddl_builder import build_create, group_foreign_keys, group_indexes

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    total_rows = 0
    done_tables = 0
    names = metadata.tables(profile, schema)
    tables = [t["name"] for t in names if t["type"] == "BASE TABLE"]
    views = [t for t in names if t["type"] == "VIEW"]
    routines = metadata.routines(profile, schema)
    triggers = metadata.triggers(profile, schema)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"-- MagicCat 全库备份 · {schema}\n\n")

        # 结构元数据一次批查（避免逐表循环查 columns/indexes/fks 的 N+1）
        cols_by, idx_rows_by, fk_rows_by = {}, {}, {}
        try:
            for r in metadata.schema_columns(profile, schema):
                cols_by.setdefault(r["table_name"], []).append(
                    {k: v for k, v in r.items() if k != "table_name"})
            for r in metadata.schema_indexes(profile, schema):
                idx_rows_by.setdefault(r["table_name"], []).append(r)
            for r in metadata.schema_foreign_keys(profile, schema):
                fk_rows_by.setdefault(r["table_name"], []).append(r)
        except Exception:  # noqa: BLE001 —— 不支持批查的产品回退逐表（仍正确，仅更慢）
            cols_by = idx_rows_by = fk_rows_by = None

        # 1) 表：结构 + 数据
        for table in tables:
            _check(cancel)
            if cols_by is not None:
                columns = cols_by.get(table, [])
                indexes = group_indexes(idx_rows_by.get(table, []))
                fks = group_foreign_keys(fk_rows_by.get(table, []))
            else:
                columns = metadata.columns(profile, schema, table)
                indexes = group_indexes(metadata.indexes(profile, schema, table))
                fks = group_foreign_keys(metadata.foreign_keys(profile, schema, table))
            if not columns:
                continue
            nullable = {c["name"]: c.get("nullable") == "YES" for c in columns}
            f.write(f"-- 表 {table}\n")
            f.write(build_create(schema, table, columns, indexes, fks) + ";\n")
            qtable = _qname(schema, table)
            headers = [c["name"] for c in columns]
            if with_data:
                offset = 0
                while True:
                    _check(cancel)
                    page = data.load_page(profile, schema, table, offset=offset, limit=1000)
                    rows = page["rows"]
                    for row in rows:
                        values = []
                        for name, v in zip(headers, row):
                            if v is None or v == "" and nullable.get(name, False):
                                values.append("NULL")
                            else:
                                values.append(_sql_string(v))
                        f.write(f"INSERT INTO {qtable} VALUES ({', '.join(values)});\n")
                    total_rows += len(rows)
                    if len(rows) < 1000:
                        break
                    offset += 1000
            done_tables += 1
            if progress:
                progress(done_tables, len(tables),
                         f"表 {done_tables}/{len(tables)}；已 {total_rows} 行")

        # 2) 视图
        for view in views:
            _check(cancel)
            f.write(f"\n-- 视图 {view['name']}\n")
            f.write(f"DROP VIEW IF EXISTS `{schema}`.`{view['name']}`;\n")
            body = ddl.show_create_view(profile, schema, view["name"]).strip()
            if not body.endswith(";"):
                body += ";"
            f.write(body + "\n")

        # 3) 存储过程/函数（含内部 ';'，用 DELIMITER 包装）
        for routine in routines:
            _check(cancel)
            kind = routine["type"].upper()  # PROCEDURE | FUNCTION
            f.write(f"\n-- {kind} {routine['name']}\n")
            body = ddl.show_create_routine(profile, schema, routine["name"], kind)
            f.write(_routine_block(body, kind, schema, routine["name"]))

        # 4) 触发器
        for trig in triggers:
            _check(cancel)
            f.write(f"\n-- 触发器 {trig['name']}\n")
            body = ddl.show_create_trigger(profile, schema, trig["name"])
            f.write(_routine_block(body, "TRIGGER", schema, trig["name"]))

    if progress:
        progress(done_tables, len(tables),
                 f"完成：表 {done_tables} · 视图 {len(views)} · 例程 {len(routines)}"
                 f" · 触发器 {len(triggers)}；{total_rows} 行")
    return {"tables": done_tables, "rows": total_rows, "views": len(views),
            "routines": len(routines), "triggers": len(triggers), "cancelled": False}


def restore_sql_file(profile: ConnectionProfile, path: str | Path,
                     query: QueryService, schema: str | None = None) -> dict:
    """执行 .sql 脚本（含备份文件）。schema 提供时在“单连接 setCatalog”上顺序执行，
    视图/例程/触发器体即使缺少库前缀也能正确落到目标库。
    返回 {statements, ok, errors:[...前10]}。
    """
    import json

    from magiccat.services.data_service import to_java_string_array
    from magiccat.services.runtime import get_runtime
    from magiccat.services.sql_text import split_sql_statements

    path = Path(path)
    text = path.read_text(encoding="utf-8")
    statements = [s for s in split_sql_statements(text) if s.strip()]
    if not statements:
        return {"statements": 0, "ok": True, "errors": []}
    if schema:
        if not query._connections.is_open(profile.id):
            query.execute(profile, "SELECT 1")  # 确保池已打开
        raw = get_runtime().jclass(
            "com.magiccat.bridge.ConnectionRegistry").executeScript(
            profile.id, schema, to_java_string_array(statements))
        results = json.loads(raw)
        errors = [r["message"] for r in results if r.get("kind") == "error"]
        return {"statements": len(results), "ok": not errors, "errors": errors[:10]}
    results = query.execute(profile, text)
    errors = [r["message"] for r in results if r.get("kind") == "error"]
    return {"statements": len(results), "ok": not errors, "errors": errors[:10]}
