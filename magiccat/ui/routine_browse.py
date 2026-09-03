"""函数领域「对象」页（对标 Navicat 函数工作区的“对象”页；函数/存储过程同组）。

- 列：名称 / 类型（FUNCTION|PROCEDURE）；操作：打开 / 新建函数 / 删除。
- 双击行 → open_routine(profile_id, name, kind)，由主窗口取 SHOW CREATE 定义打开到编辑器标签。
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from magiccat.ui.object_browse import ObjectBrowseView


class RoutineBrowseView(ObjectBrowseView):
    """函数领域·「对象」页。"""

    open_routine = Signal(str, str, str)  # profile_id, name, kind(PROCEDURE|FUNCTION)
    new_routine = Signal()
    delete_routine = Signal(str, str, str)  # profile_id, schema, name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.configure(["名称", "类型"], name_column=0,
                       new_text="新建函数", open_text="打开", delete_text="删除",
                       keys=["name", "type"])
        self.new_object.connect(self.new_routine)
        self.delete_object.connect(self._on_delete)
        self._schema: str | None = None

    def load_routines(self, profile_id: str, schema: str, rows: list[dict]) -> None:
        self._schema = schema
        self.load(profile_id, rows)

    def _selected(self) -> tuple[str, str, str] | None:
        if self._profile_id is None or not self._schema:
            return None
        name = self.selected_name()
        if not name:
            return None
        row = self._selected_row()
        typ = ""
        item = self.table.item(row, 1) if row >= 0 else None
        if item:
            typ = item.text().upper()
        kind = "FUNCTION" if typ == "FUNCTION" else "PROCEDURE"
        return self._profile_id, name, kind

    def _emit_open(self) -> None:
        sel = self._selected()
        if sel:
            self.open_routine.emit(*sel)

    def _on_delete(self, profile_id: str, name: str) -> None:
        if self._schema:
            self.delete_routine.emit(profile_id, self._schema, name)
