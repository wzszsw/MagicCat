"""触发器领域「对象」页（对标 Navicat 触发器工作区的“对象”页）。

- 列：名称 / 事件 / 表；操作：打开 / 删除（触发器通常由表内创建，故无“新建”入口）。
- 双击行 → open_trigger(profile_id, schema, name)，由主窗口取 SHOW CREATE 定义打开到编辑器标签。
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from magiccat.ui.object_browse import ObjectBrowseView


class TriggerBrowseView(ObjectBrowseView):
    """触发器领域·「对象」页。"""

    open_trigger = Signal(str, str, str)  # profile_id, schema, name
    delete_trigger = Signal(str, str, str)  # profile_id, schema, name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.configure(["名称", "事件", "表"], name_column=0,
                       new_text="新建", open_text="打开", delete_text="删除",
                       keys=["name", "event", "table"], show_new=False,
                       icon_kind="trigger")
        self.delete_object.connect(self._on_delete)
        self._schema: str | None = None

    def load_triggers(self, profile_id: str, schema: str, rows: list[dict]) -> None:
        self._schema = schema
        self.load(profile_id, rows)

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
        return {"kind": "trigger", "profile_id": sel[0], "schema": sel[1],
                "name": sel[2]}

    def _emit_open(self) -> None:
        sel = self._selected()
        if sel:
            self.open_trigger.emit(*sel)

    def _on_delete(self, profile_id: str, name: str) -> None:
        if self._schema:
            self.delete_trigger.emit(profile_id, self._schema, name)
