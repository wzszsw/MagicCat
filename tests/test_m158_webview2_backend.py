"""M158 WebView2 backend selection and package isolation regressions."""

from __future__ import annotations

import importlib


def test_webview2_backend_is_default_on_windows(monkeypatch):
    module = importlib.import_module("magiccat.ui.monaco_editor")
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.delenv("MAGICCAT_WEBVIEW", raising=False)
    monkeypatch.delenv("MAGICCAT_EDITOR", raising=False)
    assert module._use_webview2() is True


def test_qt_webengine_is_explicit_fallback(monkeypatch):
    module = importlib.import_module("magiccat.ui.monaco_editor")
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setenv("MAGICCAT_WEBVIEW", "qtwebengine")
    assert module._use_webview2() is False


def test_shared_page_supports_both_native_bridges():
    from magiccat.ui.monaco_editor import _HTML_SOURCE

    assert "chrome.webview.postMessage" in _HTML_SOURCE
    assert "qrc:///qtwebchannel/qwebchannel.js" in _HTML_SOURCE
    assert "__editor.onDidChangeCursorSelection" in _HTML_SOURCE
