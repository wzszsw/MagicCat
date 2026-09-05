"""M78 测试：顶部「其它」领域按钮（永驻）+ 序列（PG 专属菜单；MySQL 无菜单项）。"""

from __future__ import annotations

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile


def _other_button(win):
    from PySide6.QtWidgets import QToolButton
    tb = next((b for b in win.findChildren(QToolButton) if b.text() == "其它"), None)
    return tb


def test_other_button_present_and_empty_for_mysql(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    btn = _other_button(win)
    assert btn is not None, "「其它」按钮应永驻存在"
    menu = btn.menu()
    assert menu is not None
    # 模拟打开菜单（懒加载重建）
    menu.aboutToShow.emit()
    # MySQL：没有可用「其它」项 → 菜单为空
    acts = [a for a in menu.actions() if a.text()]
    assert acts == [], f"MySQL 的「其它」菜单应为空，实际: {[a.text() for a in acts]}"


def test_other_menu_has_sequence_for_pg(qtbot, connection_service, pg_env):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="PG78", group=DEFAULT_GROUP,
                                host=pg_env["host"], port=pg_env["port"],
                                username=pg_env["user"], password=pg_env["password"],
                                provider_key="PGSQL")
    connection_service.add(profile)
    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    # 选中 PG 连接 → 重建菜单应含「序列」
    win.profile_combo.setCurrentIndex(win.profile_combo.findData(profile.id))
    qtbot.waitUntil(lambda: _other_button(win) is not None, timeout=25_000)
    btn = _other_button(win)
    menu = btn.menu()
    # 菜单为懒加载（aboutToShow 时按当前连接实时重建），模拟打开菜单触发它
    menu.aboutToShow.emit()
    seq_acts = [a.text() for a in menu.actions() if a.text()]
    assert "序列" in seq_acts, f"PG 菜单应含 序列: {seq_acts}"
    connection_service.close(profile.id)


def test_show_sequence_domain(qtbot, connection_service):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win.show()
    win._show_domain("sequences")
    assert win.domain_stack.currentWidget() is win.sequence_page


def test_other_sequence_uses_latest_tree_context(qtbot, connection_service, monkeypatch):
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui.main_window import MainWindow

    win = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(win)
    win._object_context = ("profile-1", "target_db", "target_schema")
    monkeypatch.setattr(win, "_current_profile", lambda: None)
    captured: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        win, "_show_domain",
        lambda domain, schema="", database="", activate=True:
            captured.append((domain, database, schema)),
    )

    win._show_other_sequence()

    assert captured == [("sequences", "target_db", "target_schema")]


def test_sequence_load_error_uses_messagebox_not_context_label(
    qtbot, monkeypatch, connection_service
):
    from PySide6.QtWidgets import QMessageBox

    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui import main_window as main_window_module
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="序列错误", provider_key="PGSQL",
                                database="postgres")
    connection_service.add(profile)
    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox, "critical",
        staticmethod(lambda _parent, title, text, *args, **kwargs:
                     captured.append((title, text))),
    )

    def immediate(work, done, error):
        try:
            done(work())
        except Exception as exc:  # noqa: BLE001
            error(str(exc))

    monkeypatch.setattr(main_window_module, "run_async", immediate)
    monkeypatch.setattr(
        window._metadata,
        "sequences_in_database",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("java.lang.IllegalStateException: 读取序列失败")
        ),
    )

    window._reload_sequence_browse(profile, "postgres", "public")

    assert captured == [("读取序列失败", "读取序列失败")]
    assert window.sequence_page.ctx_label.text() == (
        f"{profile.display_name} · postgres · public"
    )


def test_design_sequence_ok_executes_sql_with_tree_context(
    qtbot, monkeypatch, connection_service
):
    from magiccat.services import query_service
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui import main_window as main_window_module
    from magiccat.ui.main_window import MainWindow
    from magiccat.ui.sequence_dialog import SequenceDialog

    profile = ConnectionProfile(name="设计序列", provider_key="PGSQL",
                                database="postgres")
    connection_service.add(profile)
    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    monkeypatch.setattr(
        window._metadata,
        "sequences_in_database",
        lambda *_args: [{"name": "seq", "increment": "1", "last_value": "7",
                         "start_value": "1", "min_value": "1",
                         "max_value": "100", "cache": "1", "cycle": "NO",
                         "owner": "postgres"}],
    )
    monkeypatch.setattr(window, "_reload_sequence_browse", lambda *_args: None)
    monkeypatch.setattr(
        main_window_module.QMessageBox, "information",
        staticmethod(lambda *_args, **_kwargs: None),
    )

    class _AcceptedDialog(SequenceDialog):
        def exec(self) -> int:
            return 1

        def sql(self) -> str:
            return "ALTER SEQUENCE \"public\".\"seq\" RESTART WITH 42;"

    monkeypatch.setattr("magiccat.ui.sequence_dialog.SequenceDialog", _AcceptedDialog)
    calls: list[tuple] = []

    def execute(self, *args, **kwargs):
        calls.append((args, kwargs))
        return [{"kind": "update", "affected": 0}]

    monkeypatch.setattr(query_service.QueryService, "execute", execute)
    monkeypatch.setattr(main_window_module, "run_async",
                        lambda work, done, error: done(work()))

    window._design_sequence(profile.id, "target_db", "public", "seq")

    assert calls == [((profile, 'ALTER SEQUENCE "public"."seq" RESTART WITH 42;'),
                      {"database": "target_db", "schema": "public"})]


def test_sequence_edit_sql_writes_start_and_current_values(qtbot):
    from magiccat.ui.sequence_dialog import SequenceDialog

    dialog = SequenceDialog(
        "public", "seq", mode="edit",
        data={"owner": "postgres", "increment": "1", "last_value": "7",
              "start_value": "1", "min_value": "1", "max_value": "100",
              "cache": "1", "cycle": "NO"},
    )
    qtbot.addWidget(dialog)
    dialog.start_edit.setText("11")
    dialog.current_edit.setText("42")

    sql = dialog.sql()

    assert "START WITH 11" in sql
    assert "RESTART WITH 42" in sql
