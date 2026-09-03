"""ER 图数据模型（M6）：从元数据构建 表→列 + 外键边。纯逻辑，无 UI。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TableNode:
    name: str
    columns: list[dict] = field(default_factory=list)  # {name, data_type, key}

    @property
    def height(self) -> float:
        return 46 + max(len(self.columns), 1) * 18


@dataclass
class FkEdge:
    child_table: str
    child_col: str
    parent_table: str
    parent_col: str
    name: str


@dataclass
class ErModel:
    schema: str
    tables: list[TableNode] = field(default_factory=list)
    fks: list[FkEdge] = field(default_factory=list)

    def node(self, name: str) -> TableNode | None:
        return next((t for t in self.tables if t.name == name), None)


def build_er_model(schema: str, tables: list[dict], columns_of: dict,
                   fk_rows_of: dict) -> ErModel:
    """聚合元数据为 ER 模型。

    tables: [{"name": ...}]; columns_of: {table: [列 dict]};
    fk_rows_of: {table: [外键行 dict(column_name/ref_table/ref_column)]}
    """
    model = ErModel(schema=schema)
    table_names = {t["name"] for t in tables}
    for t in tables:
        cols = []
        for c in columns_of.get(t["name"], []):
            cols.append({"name": c["name"], "data_type": c["data_type"],
                         "key": c.get("key", "")})
        model.tables.append(TableNode(name=t["name"], columns=cols))

    for child in tables:
        for fk in fk_rows_of.get(child["name"], []):
            if fk.get("ref_table") in table_names:
                model.fks.append(FkEdge(
                    child_table=child["name"],
                    child_col=fk["column_name"],
                    parent_table=fk["ref_table"],
                    parent_col=fk["ref_column"],
                    name=fk.get("constraint_name", "")))
    return model
