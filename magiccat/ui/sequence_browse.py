"""序列领域「对象」页（对标 Navicat「其它」→ 序列；PostgreSQL 专属）。

- 列：名称 / 递增 / 当前的值 / 最小 / 最大；操作：设计序列 / 新建序列 / 删除序列。
- 双击行 → design_sequence(profile_id, database, schema, name)（打开编辑/设计对话框）。
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from magiccat.ui.object_browse import ObjectBrowseView


class SequenceBrowseView(ObjectBrowseView):
    """序列领域·「对象」页。"""

    design_sequence = Signal(str, str, str, str)  # profile_id, database, schema, name
    new_sequence = Signal()
    delete_sequence = Signal(str, str, str, str)  # profile_id, database, schema, name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.configure(["名称", "递增", "当前的值", "最小", "最大"], name_column=0,
                       new_text="新建序列", open_text="设计序列", delete_text="删除序列",
                       keys=["name", "increment", "last_value", "min_value", "max_value"],
                       icon_kind="sequence")
        self.new_object.connect(self.new_sequence)
        self.delete_object.connect(self._on_delete)
        self._database: str | None = None
        self._schema: str | None = None

    def load_sequences(self, profile_id: str, database: str, schema: str,
                       rows: list[dict]) -> None:
        self._database = database
        self._schema = schema
        self.load(profile_id, rows)

    def _selected(self) -> tuple[str, str, str, str] | None:
        if self._profile_id is None or not self._database or not self._schema:
            return None
        name = self.selected_name()
        if not name:
            return None
        return self._profile_id, self._database, self._schema, name

    def _emit_open(self) -> None:
        sel = self._selected()
        if sel:
            self.design_sequence.emit(*sel)

    def _on_delete(self, profile_id: str, name: str) -> None:
        if self._database and self._schema:
            self.delete_sequence.emit(profile_id, self._database, self._schema, name)
