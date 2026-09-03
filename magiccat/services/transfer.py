"""数据传输（M5）：表导出 CSV/Excel/JSON/SQL 与 CSV 导入。

约定：
- 全程分块流式处理（不整表载入内存），支持进度回调与取消；
- 单元格 str|None；CSV/Excel 空串导出、导入时空串按列可空性转 NULL；
- 所有 DB 调用发生在调用线程（UI 须放入后台线程执行）。
"""

from __future__ import annotations

import csv
import io
import json
import threading
from collections.abc import Callable
from pathlib import Path

from magiccat.models.profile import ConnectionProfile
from magiccat.services.data_service import DataService
from magiccat.services.ddl_builder import build_create, group_foreign_keys, group_indexes
from magiccat.services.metadata_service import MetadataService
from magiccat.services.query_service import QueryService

CHUNK = 500
ProgressCb = Callable[[int, int, str], None]


class TransferCancelled(Exception):
    """用户取消（与数据库错误区分）。"""


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise TransferCancelled()


def _sql_string(v: str) -> str:
    """MySQL 字符串字面量：转义反斜杠与单引号。"""
    return "'" + v.replace("\\", "\\\\").replace("'", "''") + "'"


def _qname(schema: str, table: str) -> str:
    return f"`{schema.replace('`', '``')}`.`{table.replace('`', '``')}`"


def export_table(profile: ConnectionProfile, schema: str, table: str, path: str | Path,
                 fmt: str, data: DataService, metadata: MetadataService,
                 where: str = "", progress: ProgressCb | None = None,
                 cancel: threading.Event | None = None) -> dict:
    """导出表到文件。fmt: csv|excel|json|sql。返回 {rows, cancelled, path}。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    total = int(data.load_page(profile, schema, table, offset=0, limit=1,
                               where=where or None)["total"])
    columns_meta = metadata.columns(profile, schema, table)
    headers = [c["name"] for c in columns_meta]
    nullable = {c["name"]: c.get("nullable") == "YES" for c in columns_meta}

    if fmt == "csv":
        writer = _CsvWriter(path, headers)
    elif fmt == "excel":
        writer = _ExcelWriter(path, headers)
    elif fmt == "json":
        writer = _JsonWriter(path, headers)
    elif fmt == "sql":
        writer = _SqlWriter(profile, schema, table, path, headers, nullable, metadata)
    else:
        raise ValueError(f"不支持的导出格式: {fmt}")

    done = 0
    try:
        with writer:
            if progress:
                progress(0, total, "开始导出…")
            offset = 0
            while True:
                _check(cancel)
                page = data.load_page(profile, schema, table, offset=offset,
                                      limit=1000, where=where or None)
                rows = page["rows"]
                writer.write_rows(rows)
                done += len(rows)
                if progress:
                    progress(done, total, f"已处理 {done}/{total} 行")
                if len(rows) < 1000:
                    break
                offset += 1000
    except TransferCancelled:
        return {"rows": done, "cancelled": True, "path": str(path)}
    if progress:
        progress(done, total, "完成")
    return {"rows": done, "cancelled": False, "path": str(path)}


def import_csv(profile: ConnectionProfile, schema: str, table: str, path: str | Path,
               query: QueryService, metadata: MetadataService,
               has_header: bool = True, empty_as_null: bool = True,
               progress: ProgressCb | None = None,
               cancel: threading.Event | None = None) -> dict:
    """导入 CSV 到表。返回 {rows, cancelled, first_error}。

    已导入部分不回滚（与 Navicat 默认一致）；出错即中止剩余批次。
    """
    path = Path(path)
    columns_meta = metadata.columns(profile, schema, table)
    table_cols = [c["name"] for c in columns_meta]
    nullable = {c["name"]: c.get("nullable") == "YES" for c in columns_meta}

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return {"rows": 0, "cancelled": False, "first_error": None}

        if has_header:
            col_names = [h for h in header if h in table_cols]
        else:
            col_names = table_cols[: len(header)]
        col_index = [header.index(h) for h in col_names]
        if not col_names:
            return {"rows": 0, "cancelled": False,
                    "first_error": "CSV 表头与目标表列名无匹配（请勾选/取消首行表头）"}

        qtable = _qname(schema, table)
        col_sql = ", ".join(f"`{c.replace('`', '``')}`" for c in col_names)
        buffer: list[list] = []
        rows_done = 0
        first_error: str | None = None

        def flush() -> bool:
            nonlocal rows_done, first_error
            if not buffer:
                return True
            rows_sql = []
            for rec in buffer:
                vals = []
                for i, name in zip(col_index, col_names):
                    v = rec[i] if i < len(rec) else ""
                    if v == "" and (empty_as_null or nullable.get(name, False)):
                        vals.append("NULL")
                    else:
                        vals.append(_sql_string(v))
                rows_sql.append("(" + ", ".join(vals) + ")")
            statement = f"INSERT INTO {qtable} ({col_sql}) VALUES {', '.join(rows_sql)}"
            results = query.execute(profile, statement)
            res = results[0]
            if res.get("kind") == "error":
                first_error = res["message"]
                return False
            rows_done += len(buffer)
            buffer.clear()
            return True

        try:
            for rec in reader:
                _check(cancel)
                buffer.append(rec)
                if len(buffer) >= CHUNK and not flush():
                    break
                if progress and rows_done % (CHUNK * 10) == 0:
                    progress(rows_done, rows_done, f"已导入 {rows_done} 行")
            if first_error is None:
                flush()
        except TransferCancelled:
            if progress:
                progress(rows_done, rows_done, "已取消")
            return {"rows": rows_done, "cancelled": True, "first_error": None}
        if progress:
            progress(rows_done, rows_done, f"完成，共导入 {rows_done} 行")
        return {"rows": rows_done, "cancelled": False, "first_error": first_error}


# ---- 各格式 writer（上下文管理器，流式落盘） ----
class _CsvWriter:
    def __init__(self, path: Path, headers: list[str]) -> None:
        self._f = open(path, "w", encoding="utf-8-sig", newline="")  # noqa: SIM115 —— 由 writer 的 __exit__ 关闭
        self._w = csv.writer(self._f)
        self._w.writerow(headers)

    def write_rows(self, rows) -> None:
        self._w.writerows([["" if v is None else v for v in row] for row in rows])

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._f.close()
        return False


class _ExcelWriter:
    def __init__(self, path: Path, headers: list[str]) -> None:
        from openpyxl import Workbook

        self._path = path
        self._wb = Workbook(write_only=True)
        self._ws = self._wb.create_sheet("Sheet1")
        self._ws.append(headers)

    def write_rows(self, rows) -> None:
        for row in rows:
            self._ws.append([None if v is None else v for v in row])

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._wb.save(self._path)
        self._wb.close()
        return False


class _JsonWriter:
    def __init__(self, path: Path, headers: list[str]) -> None:
        self._f = open(path, "w", encoding="utf-8")  # noqa: SIM115 —— 由 writer 的 __exit__ 关闭
        self._f.write("[\n")
        self._headers = headers
        self._first = True

    def write_rows(self, rows) -> None:
        buf = io.StringIO()
        for row in rows:
            obj = {name: value for name, value in zip(self._headers, row)}
            if not self._first:
                buf.write(",\n")
            self._first = False
            buf.write(json.dumps(obj, ensure_ascii=False))
        self._f.write(buf.getvalue())

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._f.write("\n]\n")
        self._f.close()
        return False


class _SqlWriter:
    def __init__(self, profile, schema, table, path: Path, headers: list[str],
                 nullable: dict, metadata: MetadataService) -> None:
        columns = metadata.columns(profile, schema, table)
        indexes = group_indexes(metadata.indexes(profile, schema, table))
        fks = group_foreign_keys(metadata.foreign_keys(profile, schema, table))
        self._f = open(path, "w", encoding="utf-8")  # noqa: SIM115 —— 由 writer 的 __exit__ 关闭
        self._f.write(build_create(schema, table, columns, indexes, fks) + ";\n")
        self._qtable = _qname(schema, table)
        self._headers = headers
        self._nullable = nullable

    def write_rows(self, rows) -> None:
        buf = io.StringIO()
        for row in rows:
            values = []
            for name, v in zip(self._headers, row):
                if v is None or v == "" and self._nullable.get(name, False):
                    values.append("NULL")
                else:
                    values.append(_sql_string(v))
            buf.write(f"INSERT INTO {self._qtable} VALUES ({', '.join(values)});\n")
        self._f.write(buf.getvalue())

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._f.close()
        return False
