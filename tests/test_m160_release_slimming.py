"""M160 Windows release slimming configuration regressions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "packaging" / "pyinstaller_hooks"


def test_windows_release_keeps_translations_but_excludes_optional_qt_payloads():
    script = (ROOT / "scripts" / "build_package.ps1").read_text(encoding="utf-8")
    gui_hook = (HOOKS / "hook-PySide6.QtGui.py").read_text(encoding="utf-8")

    assert "--additional-hooks-dir $hookDir" in script
    assert "--collect-all webview" not in script
    assert "--exclude-module magiccat.ui.monaco_editor_qt" in script
    assert "--exclude-module webview.platforms.qt" in script
    assert "--exclude-module webview.platforms.winforms" in script
    assert "qwindows.dll" in gui_hook
    assert "qmodernwindowsstyle.dll" in gui_hook
    # No custom QtCore hook: the standard hook keeps all framework translations
    # available for the planned i18n work.
    assert not (HOOKS / "hook-PySide6.QtCore.py").exists()


def test_windows_release_does_not_require_local_mysql_selftest():
    windows = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    package = (ROOT / "scripts" / "build_package.ps1").read_text(encoding="utf-8")
    app = (ROOT / "magiccat" / "app.py").read_text(encoding="utf-8")

    assert "--selftest" not in windows
    assert "MAGICCAT_SELFTEST_OUTPUT" not in windows
    assert "--selftest" not in package
    assert "--selftest" not in app


def test_all_jlink_release_builds_compress_resources():
    windows = (ROOT / "scripts" / "build_package.ps1").read_text(encoding="utf-8")
    macos = (ROOT / "scripts" / "build_macos.sh").read_text(encoding="utf-8")

    assert "--compress=2" in windows
    assert "--compress=2" in macos
