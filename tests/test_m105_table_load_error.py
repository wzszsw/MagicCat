"""M105 回归：表对象页加载失败只弹错误框，不把错误写进操作栏。"""

from __future__ import annotations


def test_table_load_error_uses_messagebox_not_context_label(
    qtbot, monkeypatch, connection_service
):
    from PySide6.QtWidgets import QMessageBox

    from magiccat.models.profile import ConnectionProfile
    from magiccat.services.metadata_service import MetadataService
    from magiccat.ui import main_window as main_window_module
    from magiccat.ui.main_window import MainWindow

    profile = ConnectionProfile(name="表错误", database="test")
    connection_service.add(profile)
    window = MainWindow(connection_service, MetadataService(connection_service))
    qtbot.addWidget(window)

    captured: list[tuple[str, str]] = []

    def critical(_parent, title: str, text: str, *args, **kwargs):
        captured.append((title, text))

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(critical))

    def immediate(work, done, error):
        try:
            done(work())
        except Exception as exc:  # noqa: BLE001
            error(str(exc))

    monkeypatch.setattr(main_window_module, "run_async", immediate)
    monkeypatch.setattr(
        window._metadata,
        "schema_tables",
        lambda _profile, _schema, _database="": (_ for _ in ()).throw(
            RuntimeError("读取表失败")
        ),
    )

    window._reload_table_browse(profile, "test")

    assert captured == [("读取表失败", "读取表失败")]
    assert window.table_page.ctx_label.text() == "表错误 (127.0.0.1:3306) · test"
