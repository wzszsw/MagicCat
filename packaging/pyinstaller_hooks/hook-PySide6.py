"""Minimal Windows release hook for the PySide6 package.

MagicCat is a Widgets application.  The stock hook unconditionally bundles
the 20 MB software OpenGL renderer although the release does not use Qt Quick
or a QOpenGLWidget.  Keep the normal binding setup without that optional
fallback renderer.
"""

from PyInstaller.utils.hooks import check_requirement
from PyInstaller.utils.hooks.qt import ensure_single_qt_bindings_package

ensure_single_qt_bindings_package("PySide6")

hiddenimports = ["shiboken6", "inspect"]
# PySide6 imports QtNetwork only to probe an optional bundled OpenSSL folder.
# MagicCat's Windows release uses WinForms WebView2 and Python's ssl instead.
# At runtime PySide6 treats the missing optional import as supported fallback.
excludedimports = ["PySide6.QtNetwork"]
if check_requirement("PySide6 >= 6.4.0"):
    hiddenimports.append("PySide6.support.deprecated")
