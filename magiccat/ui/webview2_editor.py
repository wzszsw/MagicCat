"""WebView2-backed Monaco editor using pywebview's native interop package.

The WebView2 control lives in a dedicated WinForms STA thread and its child
window is parented to a native Qt widget.  This keeps the existing Qt tab and
layout experience while using the system Evergreen WebView2 runtime.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import uuid
from importlib import import_module

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from magiccat.resources import resource_dir
from magiccat.services.sql_text import split_sql_statements, statement_at_cursor
from magiccat.storage import home_dir
from magiccat.ui.monaco_editor_shared import _HTML_SOURCE, _Bridge

_DLL_DIR_HANDLE = None
_WS_CHILD = 0x40000000
_WS_CAPTION_FRAME = 0x00C00000
_SWP_NOZORDER_NOACTIVATE = 0x0014
_GWL_STYLE = -16
_SW_HIDE = 0
_SW_SHOW = 5


class _Win32Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _prepare_frozen_dll_search_path() -> None:
    """Make Python's OpenSSL DLLs discoverable before pywebview imports ssl."""
    global _DLL_DIR_HANDLE
    if not getattr(sys, "frozen", False) or os.name != "nt":
        return
    root = str(sys._MEIPASS)
    if hasattr(os, "add_dll_directory") and _DLL_DIR_HANDLE is None:
        _DLL_DIR_HANDLE = os.add_dll_directory(root)
    for name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll"):
        path = os.path.join(root, name)
        if os.path.exists(path):
            ctypes.WinDLL(path)


class _Relay(QObject):
    message = Signal(str)
    initialized = Signal(bool, str)
    script_done = Signal(str, object)


class _NativeWebView2(QWidget):
    """Host one WebView2 WinForms control inside a Qt widget."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(0, 0)
        self._relay = _Relay()
        self._control = None
        self._hwnd = 0
        self._created = queue.Queue()
        self._stopping = False
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._resize_native_window)
        self._start_thread()

    def _start_thread(self) -> None:
        # pywebview loads its bundled WebView2 .NET interop DLLs before the
        # generated Microsoft.Web namespaces are imported.
        _prepare_frozen_dll_search_path()
        import_module("webview.platforms.edgechromium")
        from Microsoft.Web.WebView2.WinForms import CoreWebView2CreationProperties, WebView2
        from System import Action
        from System.Threading import ApartmentState, Thread, ThreadStart
        from System.Windows.Forms import Application as WinFormsApplication
        self._Action = Action
        self._WinFormsApplication = WinFormsApplication

        def create() -> None:
            # WebView2 requires an STA.  Qt owns the main GUI loop, therefore
            # the WinForms control gets its own message-pump thread.
            ctypes.windll.ole32.CoInitializeEx(None, 2)
            WinFormsApplication.EnableVisualStyles()
            control = WebView2()
            properties = CoreWebView2CreationProperties()
            data_dir = home_dir() / "webview2"
            data_dir.mkdir(parents=True, exist_ok=True)
            properties.UserDataFolder = str(data_dir)
            properties.AdditionalBrowserArguments = "--disable-features=ElasticOverscroll"
            control.CreationProperties = properties
            control.CreateControl()
            self._created.put((control, int(control.Handle.ToInt64())))

            def initialized(sender, args) -> None:
                self._relay.initialized.emit(bool(args.IsSuccess), str(args.InitializationException or ""))

            def message_received(sender, args) -> None:
                try:
                    raw = str(args.get_WebMessageAsJson())
                    value = json.loads(raw)
                    if isinstance(value, str):
                        value = json.loads(value)
                    self._relay.message.emit(json.dumps(value, ensure_ascii=False))
                except (TypeError, ValueError, RuntimeError):
                    self._relay.message.emit("{}")

            control.CoreWebView2InitializationCompleted += initialized
            control.WebMessageReceived += message_received
            control.EnsureCoreWebView2Async(None)
            WinFormsApplication.Run()

        thread = Thread(ThreadStart(create))
        thread.SetApartmentState(ApartmentState.STA)
        thread.IsBackground = True
        thread.Start()
        QTimer.singleShot(0, self._poll_created)

    def _poll_created(self) -> None:
        if self._control is None:
            try:
                self._control, self._hwnd = self._created.get_nowait()
                self._attach_native_window()
            except queue.Empty:
                if not self._stopping:
                    QTimer.singleShot(10, self._poll_created)

    def _attach_native_window(self) -> None:
        parent_hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(self._hwnd, _GWL_STYLE)
        style = (style | _WS_CHILD) & ~_WS_CAPTION_FRAME
        ctypes.windll.user32.SetWindowLongW(self._hwnd, _GWL_STYLE, style)
        ctypes.windll.user32.SetParent(self._hwnd, parent_hwnd)
        self._resize_native_window()
        self._set_native_visible(self.isVisible())
        self._schedule_resize()

    def _resize_native_window(self) -> None:
        if not self._hwnd:
            return

        # QWidget dimensions are logical pixels under Windows DPI scaling,
        # while the Win32 child window uses physical client pixels.  Reading
        # the host HWND avoids a 125%/150% DPI gap on the right and bottom.
        rect = _Win32Rect()
        parent_hwnd = ctypes.c_void_p(int(self.winId()))
        if not ctypes.windll.user32.GetClientRect(parent_hwnd, ctypes.byref(rect)):
            return
        width = max(1, rect.right - rect.left)
        height = max(1, rect.bottom - rect.top)
        ctypes.windll.user32.SetWindowPos(
            ctypes.c_void_p(self._hwnd),
            ctypes.c_void_p(0),
            0,
            0,
            width,
            height,
            _SWP_NOZORDER_NOACTIVATE,
        )

    def _set_native_visible(self, visible: bool) -> None:
        if self._hwnd:
            ctypes.windll.user32.ShowWindow(self._hwnd, _SW_SHOW if visible else _SW_HIDE)

    def _schedule_resize(self) -> None:
        self._resize_timer.start(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_resize()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._set_native_visible(True)
        self._schedule_resize()

    def hideEvent(self, event) -> None:
        self._set_native_visible(False)
        super().hideEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        if self._hwnd:
            ctypes.windll.user32.SetFocus(self._hwnd)

    def invoke(self, function) -> None:
        if self._control is None or self._stopping:
            return
        try:
            self._control.BeginInvoke(self._Action(function))
        except (AttributeError, RuntimeError, TypeError):
            # The STA may already be shutting down; late UI updates are safe to
            # discard during application teardown.
            return

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        if self._control is None:
            return

        def close() -> None:
            try:
                self._control.Dispose()
            finally:
                self._WinFormsApplication.ExitThread()

        try:
            # ``invoke`` intentionally rejects new work after stopping starts;
            # teardown is the one operation that must still cross to the STA.
            self._control.BeginInvoke(self._Action(close))
        except (AttributeError, RuntimeError, TypeError):
            return

    def closeEvent(self, event) -> None:
        self.stop()
        super().closeEvent(event)


class WebView2MonacoEditorWidget(QWidget):
    """Monaco editor implementing the same public API as the Qt backend."""

    textChanged = Signal()
    selectionChanged = Signal(bool)
    readyChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._completion_data: dict = {"keywords": [], "tables": [], "columns": {}}
        self._cached_text = ""
        self._ready_flag = False
        self._core_ready = False
        self._selection_state = False
        self._selected_text = ""
        self._pending_scripts: dict[str, tuple[QEventLoop, dict]] = {}
        self._bridge = _Bridge()
        self._bridge.textChanged.connect(self.textChanged)
        self._bridge.selectionChanged.connect(self._on_selection_changed)

        self._view = _NativeWebView2(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
        self._view._relay.message.connect(self._on_message)
        self._view._relay.initialized.connect(self._on_webview_initialized)
        self._view._relay.script_done.connect(self._on_script_done)

        self._html = _HTML_SOURCE.replace("__LOADER__", "https://magiccat.local/monaco/vs/loader.js").replace(
            "__VS__", "https://magiccat.local/monaco/vs"
        )

    def load(self) -> None:
        """Retain the editor API; WebView2 starts while the widget is built."""

    def _on_webview_initialized(self, ok: bool, _error: str) -> None:
        if not ok:
            self._core_ready = False
            self._ready_flag = False
            self.readyChanged.emit(False)
            return
        self._core_ready = True
        self._navigate_html()

    def _navigate_html(self) -> None:
        root = str(resource_dir().resolve())

        def navigate() -> None:
            from Microsoft.Web.WebView2.Core import CoreWebView2HostResourceAccessKind

            core = self._view._control.CoreWebView2
            core.SetVirtualHostNameToFolderMapping("magiccat.local", root, CoreWebView2HostResourceAccessKind.Allow)
            core.NavigateToString(
                self._html.replace("<html>", '<html><head><base href="https://magiccat.local/"></head>')
            )

        self._view.invoke(navigate)
        QTimer.singleShot(50, self._poll_editor_ready)

    def _poll_editor_ready(self, attempt: int = 0) -> None:
        if self._ready_flag:
            return
        if attempt >= 160:
            self.readyChanged.emit(False)
            return

        self._evaluate("!!window.__ready && !!window.__editor", False, lambda value: self._editor_ready(value, attempt))

    def _editor_ready(self, value, attempt: int) -> None:
        if bool(value):
            self._ready_flag = True
            self.readyChanged.emit(True)
            if self._cached_text:
                self._run(f"__setValue({json.dumps(self._cached_text)})")
            self._sync_words()
        else:
            QTimer.singleShot(50, lambda: self._poll_editor_ready(attempt + 1))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.load()

    def setPlainText(self, text: str) -> None:
        self._cached_text = text or ""
        if self._selection_state:
            self._selection_state = False
            self._selected_text = ""
            self.selectionChanged.emit(False)
        self._run(f"__setValue({json.dumps(text or '')})")

    def set_value(self, text: str) -> None:
        self.setPlainText(text)

    def all_text(self) -> str:
        return self.text()

    def text(self) -> str:
        if self._ready_flag:
            value = self._evaluate("__getValue()", self._cached_text)
            if isinstance(value, str):
                self._cached_text = value
        return self._cached_text

    def toPlainText(self) -> str:
        return self.text()

    def current_sql(self) -> str | None:
        selected = self.selected_text()
        if selected is not None:
            return selected
        if self._ready_flag:
            offset = self._evaluate("__getCursorOffset()", 0)
            return statement_at_cursor(self.text(), int(offset or 0))
        return statement_at_cursor(self._cached_text, 0) if self._cached_text else None

    def selected_text(self) -> str | None:
        if self._selection_state:
            return self._selected_text.strip() or None
        if self._ready_flag:
            value = self._evaluate("__getSelection()", None)
            if value:
                start, end = int(value[0]), int(value[1])
                return self.text()[start:end].strip() or None
        return None

    def has_selection(self) -> bool:
        return self._selection_state

    def _on_selection_changed(self, selected: bool, text: str = "") -> None:
        selected = bool(selected)
        self._selected_text = (text or "") if selected else ""
        if selected != self._selection_state:
            self._selection_state = selected
            self.selectionChanged.emit(selected)

    def statements(self) -> list[str]:
        return split_sql_statements(self.text())

    def set_completion_words(self, words: list[str]) -> None:
        self.set_completion_data({"keywords": list(words or []), "tables": [], "columns": {}})

    def set_completion_data(self, data: dict) -> None:
        self._completion_data = {
            "keywords": list(data.get("keywords", []) or []),
            "tables": list(data.get("tables", []) or []),
            "columns": dict(data.get("columns", {}) or {}),
        }
        self._sync_words()

    def _sync_words(self) -> None:
        if self._ready_flag:
            self._run(f"__setCompletionData({json.dumps(self._completion_data)})")

    def cursor_pos(self) -> int:
        return int(self._evaluate("__getCursorOffset()", 0) or 0)

    def _on_message(self, payload: str) -> None:
        try:
            message = json.loads(payload)
            method = message.get("method")
            args = message.get("args") or []
            if method == "emitChanged":
                self._bridge.emitChanged()
            elif method == "emitSelectionChanged":
                self._bridge.emitSelectionChanged(bool(args[0]), str(args[1] or ""))
        except (TypeError, ValueError, IndexError):
            return

    def _run(self, script: str) -> None:
        if not self._view._control or not self._core_ready:
            return
        self._view.invoke(lambda: self._view._control.ExecuteScriptAsync(script))

    def _evaluate(self, script: str, fallback=None, callback=None):
        if not self._view._control or not self._core_ready:
            return fallback
        token = uuid.uuid4().hex
        result = {"value": fallback}
        loop = QEventLoop() if callback is None else None
        if callback is not None:
            result["callback"] = callback
        self._pending_scripts[token] = (loop, result)

        def execute() -> None:
            from System import Action
            from System.Threading.Tasks import Task

            def completed(task) -> None:
                try:
                    value = json.loads(str(task.Result))
                except (TypeError, ValueError, RuntimeError):
                    value = fallback
                self._view._relay.script_done.emit(token, value)

            self._view._control.ExecuteScriptAsync(script).ContinueWith(Action[Task[str]](completed))

        self._view.invoke(execute)
        if callback is not None:
            return None
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        self._pending_scripts.pop(token, None)
        return result["value"]

    def _on_script_done(self, token: str, value) -> None:
        pending = self._pending_scripts.pop(token, None)
        if pending is None:
            return
        loop, result = pending
        result["value"] = value
        if loop is not None:
            loop.quit()
        else:
            callback = result.get("callback")
            if callback:
                callback(value)
