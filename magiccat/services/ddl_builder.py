"""DDL 生成与变更对比（纯 Python，无 DB 依赖）。

列定义 dict 约定（与 MetadataService.columns 对齐）：
    name, data_type(完整类型如 varchar(50)), nullable("NO"/"YES"),
    default_value(str|None), extra(含 "auto_increment"), comment, key("PRI"/...)
"""

from __future__ import annotations

from collections import OrderedDict


def _q(name: str) -> str:
    return "`" + str(name).replace("`", "``") + "`"


def _default_literal(value: str | None) -> str:
    """默认值字面量：数字/表达式/已引号包裹的原样；其余单引号包裹并转义。"""
    if value is None:
        return ""
    v = value.strip()
    if v == "" or v.upper() == "NULL":
        return ""
    if v.startswith(("(", "'", '"')) or v.replace(".", "", 1).isdigit():
        return v
    return "'" + v.replace("'", "''") + "'"


def column_def(col: dict) -> str:
    """单列定义文本（不含 KEY 前缀，可作 ADD/MODIFY COLUMN 的右部）。"""
    parts = [_q(col["name"]), col["data_type"]]
    nullable = col.get("nullable", "NO") != "YES"
    if nullable and col.get("key") != "PRI":
        parts.append("NOT NULL")
    default = _default_literal(col.get("default_value"))
    if default:
        parts.append("DEFAULT " + default)
    if "auto_increment" in (col.get("extra") or "").lower():
        parts.append("AUTO_INCREMENT")
    comment = (col.get("comment") or "").strip()
    if comment:
        parts.append("COMMENT " + "'" + comment.replace("'", "''") + "'")
    return " ".join(parts)


def group_indexes(index_rows: list[dict]) -> list[dict]:
    """information_schema.STATISTICS 行（每列一行）→ [{index_name, non_unique, columns:[...]}]。"""
    groups: OrderedDict[str, dict] = OrderedDict()
    for r in index_rows:
        name = str(r["index_name"])
        g = groups.setdefault(name, {"index_name": name, "columns": []})
        g.setdefault("non_unique", r["non_unique"])
        g["columns"].append((int(r["seq"]), str(r["column_name"])))
    for g in groups.values():
        g["columns"] = [c for _, c in sorted(g["columns"])]
    return list(groups.values())


def group_foreign_keys(fk_rows: list[dict]) -> list[dict]:
    """KEY_COLUMN_USAGE 外键行（每列一行）→ [{constraint_name, columns, ref_table,
    ref_columns, on_update, on_delete}]（多列外键按列序聚合）。"""
    groups: OrderedDict[str, dict] = OrderedDict()
    for r in fk_rows:
        name = str(r["constraint_name"])
        g = groups.setdefault(name, {"constraint_name": name})
        g.setdefault("ref_table", r["ref_table"])
        g.setdefault("columns", [])
        g.setdefault("ref_columns", [])
        g["columns"].append(str(r["column_name"]))
        g["ref_columns"].append(str(r["ref_column"]))
        g["on_update"] = r.get("on_update")
        g["on_delete"] = r.get("on_delete")
    return list(groups.values())


def build_create(schema: str, table: str, columns: list[dict],
                 indexes: list[dict] | None = None,
                 foreign_keys: list[dict] | None = None,
                 engine: str = "InnoDB DEFAULT CHARSET=utf8mb4") -> str:
    """生成 CREATE TABLE 语句。indexes/fks 请先经 group_* 聚合。"""
    body: list[str] = []
    pk = [c["name"] for c in columns if c.get("key") == "PRI"]
    for c in columns:
        cd = column_def(c)
        if c.get("key") == "PRI":
            cd = cd.replace("NOT NULL ", "")  # 主键列非空由表级约束隐含
        body.append(cd)
    if pk:
        body.append("PRIMARY KEY (" + ", ".join(_q(n) for n in pk) + ")")
    for idx in indexes or []:
        if str(idx["index_name"]).upper() == "PRIMARY":
            continue
        unique = "UNIQUE " if _is_false(idx.get("non_unique")) else ""
        body.append(f"{unique}KEY {_q(idx['index_name'])} ("
                    + ", ".join(_q(c) for c in idx["columns"]) + ")")
    for fk in foreign_keys or []:
        on_delete = f" ON DELETE {fk['on_delete']}" if fk.get("on_delete") else ""
        on_update = f" ON UPDATE {fk['on_update']}" if fk.get("on_update") else ""
        body.append(
            f"CONSTRAINT {_q(fk['constraint_name'])} FOREIGN KEY ("
            + ", ".join(_q(c) for c in fk["columns"]) + ") REFERENCES "
            + f"{_q(schema)}.{_q(fk['ref_table'])} ("
            + ", ".join(_q(c) for c in fk["ref_columns"]) + ")"
            + on_delete + on_update)
    lines = [f"CREATE TABLE {_q(schema)}.{_q(table)} ("]
    lines.append(",\n  ".join(body))
    lines.append(f") ENGINE={engine}")
    return "\n".join(lines)


def _is_false(v) -> bool:
    return v in (0, "0", False, "false", "no", "NO")


def alter_fragments(original: list[dict], edited: list[dict]) -> list[str]:
    """对比原列与编辑后的列，返回 ALTER TABLE 的变更片段（ADD/DROP/MODIFY COLUMN）。

    重命名列：视作 删除旧列 + 新增新列（保守且无歧义）。
    """
    old_by_name = {c["name"]: c for c in original}
    edited_names = {c["name"] for c in edited}
    fragments: list[str] = []
    for name in old_by_name:
        if name not in edited_names:
            fragments.append(f"DROP COLUMN {_q(name)}")
    for col in edited:
        old = old_by_name.get(col["name"])
        if old is None:
            fragments.append(f"ADD COLUMN {column_def(col)}")
        elif not _same_def(old, col):
            fragments.append(f"MODIFY COLUMN {column_def(col)}")
    return fragments


def _same_def(a: dict, b: dict) -> bool:
    def norm(d: dict) -> tuple:
        return (d["data_type"].lower().replace(" ", ""),
                d.get("nullable"),
                (d.get("default_value") or "").strip().lower(),
                (d.get("comment") or "").strip(),
                bool("auto_increment" in (d.get("extra") or "").lower()))

    return norm(a) == norm(b)
