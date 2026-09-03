"""查询领域「对象」页（对标 Navicat 查询工作区的“对象”页）。

- 列：名称 / 修改日期 / 库；操作：新建查询 / 删除查询（“设计查询”=查询构建工具，属高级功能，本轮不做）。
- 双击行 → open_query(profile_id, name)，由主窗口切到编辑态标签并载入。
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from magiccat.services import query_library
from magiccat.ui.object_browse import ObjectBrowseView


class QueryBrowseView(ObjectBrowseView):
    """查询领域·「对象」页。"""

    open_query = Signal(str, str)  # profile_id, name
    new_query = Signal()
    delete_query = Signal(str, str)  # profile_id, name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.configure(["名称", "修改日期", "库"], name_column=0,
                       new_text="新建查询", open_text="打开", delete_text="删除查询",
                       keys=["name", "updated_at", "schema"])
        self.open_object.connect(self.open_query)
        self.new_object.connect(self.new_query)
        self.delete_object.connect(self.delete_query)

    def load_queries(self, profile_id: str, schema: str) -> None:
        items = query_library.QueryLibrary.default().list(profile_id)
        rows = [q for q in items if (q.get("schema") or "") == schema]
        self.load(profile_id, rows)

    def _selection_desc(self) -> dict | None:
        if self._profile_id is None:
            return None
        name = self.selected_name()
        if not name:
            return None
        row = self._selected_row()
        schema = ""
        item = self.table.item(row, 2) if row >= 0 else None
        if item:
            schema = item.text()
        return {"kind": "saved_query", "profile_id": self._profile_id,
                "schema": schema, "name": name}
