"""M75 测试：对象树 loading 动画图标（start 动画化 / stop 恢复原图标）。"""

from __future__ import annotations

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


def test_loading_icon_start_and_stop(qtbot):
    from magiccat.ui import loading

    tree = QTreeWidget()
    qtbot.addWidget(tree)
    node = QTreeWidgetItem(["t"])
    tree.addTopLevelItem(node)
    orig = node.icon(0)

    loading.start_loading(node)
    assert id(node) in loading._active
    assert node.icon(0).cacheKey() != orig.cacheKey()
    state = loading._active[id(node)]
    state._tick()  # 推进一帧
    assert state.idx == 1 or state.idx in range(loading._STEPS)

    loading.stop_loading(node)
    assert id(node) not in loading._active
    assert node.icon(0).cacheKey() == orig.cacheKey()


def test_loading_icon_idempotent_start(qtbot):
    from magiccat.ui import loading

    tree = QTreeWidget()
    qtbot.addWidget(tree)
    node = QTreeWidgetItem(["t"])
    tree.addTopLevelItem(node)

    loading.start_loading(node)
    loading.start_loading(node)  # 不叠加
    assert len([k for k in loading._active if k == id(node)]) == 1
    loading.stop_loading(node)
    assert id(node) not in loading._active
