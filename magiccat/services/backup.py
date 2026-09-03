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


def restore_sql_file(profile: ConnectionProfile, path: str | Path,
                     query: QueryService) -> dict:
    """执行 .sql 脚本（含备份文件）。返回 {statements, ok, errors:[...前10]}。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    results = query.execute(profile, text)
    errors = [r["message"] for r in results if r.get("kind") == "error"]
    return {"statements": len(results), "ok": not errors, "errors": errors[:10]}
