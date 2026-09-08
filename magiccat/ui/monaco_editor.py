"""Monaco editor backend selection.

Windows release builds use pywebview's WebView2 interop so the Evergreen
WebView2 runtime remains a system dependency.  Qt WebEngine stays available as
an explicit fallback (``MAGICCAT_WEBVIEW=qtwebengine``) and for non-Windows.

The WebView2 backend requires the Microsoft Evergreen WebView2 Runtime.  The
Windows installer should detect/install that runtime separately; it is not
copied into the MagicCat package.
"""

from __future__ import annotations

import os

from magiccat.ui.monaco_editor_shared import _HTML_SOURCE, _Bridge


def _use_webview2() -> bool:
    if os.environ.get("MAGICCAT_WEBVIEW", "").strip().lower() in {"qt", "qtwebengine"}:
        return False
    if os.name != "nt":
        return False
    # Do not probe/import the backend here. PyInstaller may resolve pythonnet's
    # .NET assemblies differently before the application directory is ready,
    # which would incorrectly select the source-only Qt fallback. WebView2
    # reports a missing Evergreen Runtime through its initialization signal.
    return os.environ.get("MAGICCAT_EDITOR", "").strip().lower() != "plain"


if _use_webview2():
    from magiccat.ui.webview2_editor import WebView2MonacoEditorWidget as MonacoEditorWidget
else:
    from importlib import import_module

    MonacoEditorWidget = import_module("magiccat.ui.monaco_editor_qt").MonacoEditorWidget


__all__ = ["_HTML_SOURCE", "MonacoEditorWidget", "_Bridge"]
