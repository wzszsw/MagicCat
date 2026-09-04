"""M87：GaussDB 方言、全局环境驱动配置与 PG 兼容对象语义。"""

from __future__ import annotations

from magiccat.models.profile import ConnectionProfile


def test_gaussdb_profile_uses_postgres_compatible_semantics() -> None:
    profile = ConnectionProfile(name="Gauss", provider_key="gaussdb")

    assert profile.is_postgres


def test_pg_and_gaussdb_initial_database_is_required(qtbot) -> None:
    from magiccat.ui.dialogs import ConnectionEditDialog

    dialog = ConnectionEditDialog()
    qtbot.addWidget(dialog)
    dialog._select_product("gaussdb")
    dialog.name_edit.setText("Gauss")
    dialog.db_edit.clear()
    assert dialog.type_combo.currentData() == "gaussdb"
    assert not dialog.db_edit.text()


def test_pg_and_gaussdb_edit_default_initial_database(qtbot) -> None:
    from magiccat.ui.dialogs import ConnectionEditDialog

    for provider in ("postgresql", "gaussdb"):
        dialog = ConnectionEditDialog(
            profile=ConnectionProfile(name="Existing", provider_key=provider))
        qtbot.addWidget(dialog)
        assert dialog.db_edit.text() == "postgres"


def test_gaussdb_requires_environment_driver(monkeypatch, tmp_path) -> None:
    from magiccat.services.connection_service import ConnectionService

    monkeypatch.setenv("MAGICCAT_HOME", str(tmp_path))
    profile = ConnectionProfile(name="Gauss", provider_key="gaussdb")

    try:
        ConnectionService._driver_jar(profile)
    except ValueError as exc:
        assert "工具 → 环境" in str(exc)
    else:
        raise AssertionError("未指定环境驱动时应明确报错")


def test_environment_dialog_persists_global_driver(qtbot, monkeypatch, tmp_path) -> None:
    from magiccat.services.settings import AppSettings
    from magiccat.ui.dialogs import EnvironmentDialog

    monkeypatch.setenv("MAGICCAT_HOME", str(tmp_path))
    driver = tmp_path / "gaussdbjdbc.jar"
    driver.touch()
    dialog = EnvironmentDialog()
    qtbot.addWidget(dialog)
    dialog.gaussdb_driver_edit.setText(str(driver))
    dialog._save()

    assert AppSettings.default().get("gaussdb_driver_jar") == str(driver)


def test_gaussdb_uses_github_huawei_icon(qtbot) -> None:
    from magiccat.ui.icons import icon

    logo = icon("profile", "gaussdb")
    assert not logo.isNull()


def test_connection_combo_items_include_product_icons(qtbot) -> None:
    from PySide6.QtWidgets import QComboBox

    from magiccat.models.profile import ConnectionProfile
    from magiccat.ui.profile_combo import populate_profile_combo

    combo = QComboBox()
    qtbot.addWidget(combo)
    profiles = [
        ConnectionProfile(name="MySQL", provider_key="mysql"),
        ConnectionProfile(name="GaussDB", provider_key="gaussdb"),
    ]
    populate_profile_combo(combo, profiles)

    assert combo.count() == 2
    assert not combo.itemIcon(0).isNull()
    assert not combo.itemIcon(1).isNull()
    assert combo.itemData(1) == profiles[1].id
