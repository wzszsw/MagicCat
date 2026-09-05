"""表领域「对象」页（对标 Navicat 表工作区的“对象”页）。

- 列：名称 / 类型 / 引擎 / 行数 / 注释；操作：打开表 / 设计表 / 新建表 / 删除表。
  （导入向导 / 导出向导暂不做。）
- 双击行 → open_table(profile_id, schema, name)，由主窗口打开表数据编辑标签。
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from magiccat.ui.object_browse import ObjectBrowseView


class TableBrowseView(ObjectBrowseView):
    """表领域·「对象」页。"""

    open_table = Signal(str, str, str)  # profile_id, schema, name
    design_table = Signal(str, str, str)  # profile_id, schema, name
    new_table = Signal()
    delete_table = Signal(str, str, str)  # profile_id, schema, name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.configure(["名称", "类型", "引擎", "行数", "注释"], name_column=0,
                       new_text="新建表", open_text="打开", delete_text="删除表",
                       keys=["name", "type", "engine", "rows", "comment"])
        self.add_tool_button("设计表", self._emit_design)
        self.new_object.connect(self.new_table)
        self.delete_object.connect(self._on_delete)
        self._schema: str | None = None
        self._database = ""

    def load_tables(self, profile_id: str, schema: str, rows: list[dict],
                    database: str = "") -> None:
        self._database = database or ""
        self._schema = schema
        self.load(profile_id, rows)

    def database_context(self) -> str:
        """返回对象页加载时的 JDBC catalog/database。"""
        return self._database

    def _selected(self) -> tuple[str, str, str] | None:
        if self._profile_id is None or not self._schema:
            return None
        name = self.selected_name()
        if not name:
            return None
        return self._profile_id, self._schema, name

    def _selection_desc(self) -> dict | None:
        sel = self._selected()
        if not sel:
            return None
        return {"kind": "table", "profile_id": sel[0], "schema": sel[1],
                "name": sel[2], "table": sel[2]}

    # 双击“打开”→ 打开表数据；打开按钮亦同
    def _emit_open(self) -> None:
        sel = self._selected()
        if sel:
            self.open_table.emit(*sel)

    def _emit_design(self) -> None:
        sel = self._selected()
        if sel:
            self.design_table.emit(*sel)

    def _on_delete(self, profile_id: str, name: str) -> None:
        if self._schema:
            self.delete_table.emit(profile_id, self._schema, name)
