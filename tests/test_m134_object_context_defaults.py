"""M134 回归：初始化库不冒充对象页当前库；树节点双击直接展开。"""

from __future__ import annotations


def test_mysql_connection_form_has_no_database_field(qtbot):
    from magiccat.models.profile import ConnectionProfile
    from magiccat.ui.dialogs import ConnectionEditDialog

    dialog = ConnectionEditDialog(
        profile=ConnectionProfile(name="mysql", provider_key="MYSQL", database="legacy")
    )
    qtbot.addWidget(dialog)

    assert dialog._database_label.isHidden()
    assert dialog.db_edit.isHidden()
    assert dialog.profile().database == ""


def test_object_browse_does_not_fall_back_to_profile_database(
    qtbot, connection_service, monkeypatch
):
    from magiccat.models.profile import ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui import main_window as main_window_module
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="mysql", database="initial")
    connection_service.add(profile)
    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        window._metadata,
        "schema_tables",
        lambda _profile, schema, database="": calls.append((schema, database)) or [],
    )
    monkeypatch.setattr(
        main_window_module,
        "run_async",
        lambda work, done, _error: done(work()),
    )

    window._reload_table_browse(profile)
    assert calls == [("", "")]

    window._object_context = (profile.id, "target_db", "target_db")
    window._reload_table_browse(profile)
    assert calls[-1] == ("target_db", "target_db")


def test_tree_double_click_toggles_expand_without_triangle(qtbot, connection_service):
    from magiccat.models.profile import ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow
    from magiccat.ui.object_explorer import _make_item

    profile = ConnectionProfile(name="tree")
    connection_service.add(profile)
    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)
    item = window.explorer.profile_item(profile.id)
    assert item is not None
    item.addChild(_make_item("database", "database", schema="database"))
    item.setExpanded(False)

    window.explorer._on_double_clicked(item, 0)
    assert item.isExpanded()
    window.explorer._on_double_clicked(item, 0)
    assert not item.isExpanded()


def test_postgres_database_selection_does_not_invent_public_schema(
    qtbot, connection_service, monkeypatch
):
    from magiccat.models.profile import ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.object_explorer import ObjectExplorer, _make_item

    profile = ConnectionProfile(name="pg", provider_key="PGSQL",
                                database="postgres")
    connection_service.add(profile)
    monkeypatch.setattr(connection_service, "is_open", lambda _pid: True)
    explorer = ObjectExplorer(connection_service, MetadataService(connection_service))
    qtbot.addWidget(explorer)
    explorer.load_profiles()
    profile_item = explorer.profile_item(profile.id)
    assert profile_item is not None
    profile_item.takeChildren()
    database_item = _make_item("target", "database", schema="target")
    profile_item.addChild(database_item)

    contexts: list[tuple[str, str, str, str]] = []
    explorer.object_context_selected.connect(
        lambda pid, database, schema, cat: contexts.append(
            (pid, database, schema, cat)
        )
    )
    explorer.setCurrentItem(database_item)

    assert contexts == [(profile.id, "target", "", "tables")]
