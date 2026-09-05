"""M132 回归：对象树双击视图/触发器走对应定义编辑入口。"""

from __future__ import annotations


def test_tree_double_click_routes_view_and_trigger(qtbot, monkeypatch) -> None:
    from types import SimpleNamespace

    from magiccat.ui.object_explorer import ObjectExplorer, _make_item

    explorer = ObjectExplorer(None, None)
    qtbot.addWidget(explorer)
    monkeypatch.setattr(explorer, "_profile_of", lambda _item: SimpleNamespace(id="pid"))
    group = _make_item("g", "group")
    profile = _make_item("p", "profile", profile_id="pid")
    group.addChild(profile)
    explorer.addTopLevelItem(group)

    views = []
    triggers = []
    explorer.open_view_requested.connect(lambda *args: views.append(args))
    explorer.open_trigger_requested.connect(lambda *args: triggers.append(args))

    view = _make_item("v", "view", schema="db", table="v", name="v")
    trigger = _make_item("tr", "trigger", schema="db", name="tr")
    profile.addChild(view)
    profile.addChild(trigger)

    explorer._on_double_clicked(view, 0)
    explorer._on_double_clicked(trigger, 0)

    assert views == [("pid", "db", "v")]
    assert triggers == [("pid", "db", "tr")]
