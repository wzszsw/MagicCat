"""Collect the Windows platform integration, not every optional Qt GUI plugin."""

from pathlib import Path

from PyInstaller.utils.hooks.qt import pyside6_library_info

hiddenimports = ["PySide6.QtCore"]
_plugins = Path(pyside6_library_info.location["PluginsPath"])
_qt_plugins = Path(pyside6_library_info.qt_rel_dir) / "plugins"
binaries = [
    (str(_plugins / "platforms" / "qwindows.dll"),
     str(_qt_plugins / "platforms")),
    (str(_plugins / "styles" / "qmodernwindowsstyle.dll"),
     str(_qt_plugins / "styles")),
]
