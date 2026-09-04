"""SQL 编辑器（monaco-editor 封装，对标 VS Code 内核）。

- QWebEngineView 加载本地 monaco-editor 资源（magiccat/resources/monaco，离线可用）。
- 通过 QWebChannel 与页面双向通信：Python→JS 设值/注入补全；JS→Python 通知文本变化。
- 对外接口与旧 SqlEditorWidget 兼容：text()/all_text()/current_sql()/set_completion_words()。
- 语法高亮由 monaco 的 SQL 语言服务提供（减轻自研高亮成本）。
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from magiccat.resources import resource_dir
from magiccat.services.sql_text import split_sql_statements, statement_at_cursor

_HTML_SOURCE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html, body, #container { height: 100%; margin: 0; padding: 0; }
</style></head>
<body>
<div id="container"></div>
<script src="__LOADER__"></script>
<script>
require.config({ paths: { 'vs': '__VS__' } });
var __bridge = null;
var __editor = null;
require(['vs/editor/editor.main', 'vs/basic-languages/sql/sql'], function () {
  __editor = monaco.editor.create(document.getElementById('container'), {
    value: '',
    language: 'sql',
    theme: 'vs',
    automaticLayout: true,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
  });
  __editor.onDidChangeModelContent(function () {
    if (__bridge) { __bridge.emitChanged(); }
  });
  window.__ready = true;
});
function __setValue(v) { if (__editor) __editor.setValue(v || ''); }
function __getValue() { return __editor ? __editor.getValue() : ''; }
function __getCursorOffset() {
  if (!__editor) return 0;
  var p = __editor.getPosition();
  return __editor.getModel().getOffsetAt(p);
}
function __getSelection() {
  if (!__editor) return null;
  var s = __editor.getSelection();
  if (!s || s.isEmpty()) return null;
  var m = __editor.getModel();
  return [m.getOffsetAt(s.getStartPosition()), m.getOffsetAt(s.getEndPosition())];
}
function __setCompletionWords(words) {
  if (!__editor || !monaco) return;
  monaco.languages.registerCompletionItemProvider('sql', {
    triggerCharacters: [' ', '(', ','],
    provideCompletionItems: function (model, position) {
      var word = model.getWordUntilPosition(position);
      var span = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber,
                    startColumn: word.startColumn, endColumn: word.endColumn };
      var suggestions = (words || []).map(function (w) {
        return { label: w, kind: monaco.languages.CompletionItemKind.Keyword,
                  insertText: w, range: span };
      });
      return { suggestions: suggestions };
    }
  });
}
</script>
</body></html>
"""


class _Bridge(QObject):
    """Python↔JS 桥：JS 侧调 emitChanged 通知文本变化。"""

    textChanged = Signal()

    @Slot()
    def emitChanged(self) -> None:  # pragma: no cover
        self.textChanged.emit()


class MonacoEditorWidget(QWidget):
    """单标签 SQL 编辑器（monaco 内核）。"""

    textChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._completion_words: list[str] = []
        self._cached_text = ""
        self._ready_flag = False
        self._bridge = _Bridge()
        self._bridge.textChanged.connect(self.textChanged)

        self._view = QWebEngineView(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        self._view.page().setWebChannel(self._channel)

        self._html = (_HTML_SOURCE
                      .replace("__LOADER__", _url("monaco/vs/loader.js"))
                      .replace("__VS__", _url("monaco/vs")))

    def load(self) -> None:
        """加载页面（必须在 show 之后调用，交给上层）。"""
        self._view.loadFinished.connect(self._on_loaded)
        self._view.setHtml(self._html, baseUrl=QUrl("file://"))

    def _on_loaded(self, ok: bool) -> None:
        if ok:
            self._view.page().runJavaScript(
                "(function(){ return !!window.__editor; })()", 0, self._after_editor_ready)

    def _after_editor_ready(self, has_editor) -> None:
        self._ready_flag = bool(has_editor)
        self._sync_words()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._view.url().isValid():
            self.load()

    # ---- 文本写入 ----
    def setPlainText(self, text: str) -> None:
        self._cached_text = text or ""
        self._run(f"__setValue({json.dumps(text or '')})")

    def set_value(self, text: str) -> None:
        self.setPlainText(text)

    # ---- 对外文本接口 ----
    def all_text(self) -> str:
        return self.text()

    def text(self) -> str:
        """取编辑器全文。优先取最新（页面已就绪时同步 JS），否则用缓存副本。"""
        if self._ready():
            v = self._evaluate("__getValue()", None)
            if isinstance(v, str):
                self._cached_text = v
                return v
        return self._cached_text

    def toPlainText(self) -> str:
        return self.text()

    def current_sql(self) -> str | None:
        """选中文本优先；否则光标所在语句。"""
        if self._ready():
            sel = self._evaluate("__getSelection()", None)
            if sel:
                start, end = int(sel[0]), int(sel[1])
                text = self.text()
                return text[start:end].strip() or None
            offset = self._evaluate("__getCursorOffset()", 0)
            return statement_at_cursor(self.text(), int(offset or 0))
        return statement_at_cursor(self._cached_text, 0) if self._cached_text else None

    def statements(self) -> list[str]:
        return split_sql_statements(self.text())

    # ---- 补全 ----
    def set_completion_words(self, words: list[str]) -> None:
        self._completion_words = list(words)
        self._sync_words()

    def _sync_words(self) -> None:
        if not self._ready():
            return
        self._view.page().runJavaScript(
            f"__setCompletionWords({json.dumps(self._completion_words)})", 0)

    def cursor_pos(self) -> int:
        return int(self._evaluate("__getCursorOffset()", 0) or 0)

    # ---- 内部：JS 求值 ----
    def _ready(self) -> bool:
        return self._ready_flag

    def _run(self, js: str) -> None:
        self._view.page().runJavaScript(js, 0)

    def _evaluate(self, js: str, fallback):
        # runJavaScript 是异步回调；用同步子事件循环等待结果
        from PySide6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        out = {"v": None}
        self._view.page().runJavaScript(js, 0, lambda r: (out.__setitem__("v", r), loop.quit()))
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        return out.get("v") if out.get("v") is not None else fallback


def _url(rel: str) -> str:
    return (resource_dir() / rel).as_uri()
