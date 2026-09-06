"""M156 回归：启动画面独立于尚未显示的主窗口。"""

from __future__ import annotations


def test_startup_splash_has_product_identity_and_loading_state(qtbot) -> None:
    from magiccat.ui.startup_splash import StartupSplash

    splash = StartupSplash()
    qtbot.addWidget(splash)

    assert splash.windowTitle() == "MagicCat"
    assert splash.width() == 520
    assert splash.height() == 340
    assert splash._timer.interval() == 90
