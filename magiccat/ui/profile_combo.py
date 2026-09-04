"""带数据库产品图标的连接选择下拉框辅助函数。"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import QComboBox

from magiccat.models.profile import ConnectionProfile


def add_profile_item(combo: QComboBox, profile: ConnectionProfile) -> None:
    """向连接选择框加入一个带产品图标的连接条目。"""
    from magiccat.ui.icons import icon

    combo.addItem(icon("profile", profile.provider_key), profile.display_name, profile.id)


def populate_profile_combo(combo: QComboBox, profiles: Iterable[ConnectionProfile],
                           placeholder: str | None = None) -> None:
    """清空并填充连接选择框；placeholder 仅用于未选择状态。"""
    current_id = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    if placeholder is not None:
        combo.addItem(placeholder, None)
    for profile in profiles:
        add_profile_item(combo, profile)
    if current_id:
        index = combo.findData(current_id)
        if index >= 0:
            combo.setCurrentIndex(index)
    combo.blockSignals(False)
