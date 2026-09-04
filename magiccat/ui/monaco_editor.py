"""SQL 编辑器（monaco-editor 封装，对标 VS Code 内核）。

- QWebEngineView 加载本地 monaco-editor 资源（magiccat/resources/monaco，离线可用）。
- 通过 QWebChannel 与页面双向通信：Python→JS 设值/注入补全；JS→Python 通知文本和选区变化。
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

_HTML_SOURCE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html, body, #container { height: 100%; margin: 0; padding: 0; }
</style></head>
<body>
<div id="container"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="__LOADER__"></script>
<script>
require.config({ paths: { 'vs': '__VS__' } });
var __bridge = null;
var __editor = null;
function __emitSelectionState() {
  if (__bridge && __editor) {
    var selection = __editor.getSelection();
    var selected = !!selection && !selection.isEmpty();
    var text = selected ? __editor.getModel().getValueInRange(selection) : '';
    __bridge.emitSelectionChanged(selected, text);
  }
}
new QWebChannel(qt.webChannelTransport, function (channel) {
  __bridge = channel.objects.bridge;
  __emitSelectionState();
});
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
  __editor.onDidChangeCursorSelection(function () {
    __emitSelectionState();
  });
  __emitSelectionState();
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
var __CDATA = { keywords: [], tables: [], columns: {} };
function __completionFor(text, data) {
  var CDATA = data || __CDATA;
  var TABLE_CTX = ['FROM','JOIN','INTO','UPDATE','TABLE','REFERENCES','DELETE'];
  var COL_CTX = ['SELECT','WHERE','ON','HAVING','AND','OR','BY','GROUP','ORDER','SET'];
  var up = (text || '').toUpperCase();
  var out = [];
  function push(label) {
    if (out.indexOf(label) < 0) out.push(label);
  }
  var dotM = (text || '').match(/([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)?$/);
  if (dotM) {
    var beforeDot = (text || '').slice(0, dotM.index);
    if (/\b(FROM|JOIN|INTO|UPDATE|TABLE|REFERENCES)\s+[^;]*$/i.test(beforeDot)) {
      var tablePrefix = (dotM[2] || '').toLowerCase();
      (CDATA.tables || []).forEach(function (t) {
        if (!tablePrefix || String(t.name).toLowerCase().indexOf(tablePrefix) === 0) push(t.name);
      });
    return out;
}
    var sourceName = dotM[1];
    var aliasMatch = (text || '').match(/\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)[^;]*$/i);
    var tableName = aliasMatch && aliasMatch[2].toLowerCase() === sourceName.toLowerCase()
      ? aliasMatch[1] : sourceName;
    var columnList = CDATA.columns[sourceName] || CDATA.columns[sourceName.toLowerCase()] ||
      CDATA.columns[tableName] || CDATA.columns[tableName.toLowerCase()] || [];
    var prefix = (dotM[2] || '').toLowerCase();
    columnList.forEach(function (column) {
      if (!prefix || String(column).toLowerCase().indexOf(prefix) === 0) push(column);
    });
    return out;
  }
  var lkM = up.match(/(\b[A-Z]+)\s*$/);
  var lk = lkM ? lkM[1] : '';
  var tableCtxM = up.match(/\b(FROM|JOIN|INTO|UPDATE|TABLE|REFERENCES|DELETE)\s+([A-Z0-9_]*)$/);
  if (tableCtxM) {
    var tablePrefix = tableCtxM[2].toLowerCase();
    (CDATA.tables || []).forEach(function (t) {
      if (!tablePrefix || String(t.name).toLowerCase().indexOf(tablePrefix) === 0) push(t.name);
    });
    return out;
  }
  if (COL_CTX.indexOf(lk) >= 0) {
    var seen = {};
    (CDATA.tables || []).forEach(function (t) {
      (CDATA.columns[t.name] || []).forEach(function (c) { if (!seen[c]) { seen[c] = 1; push(c); } });
    });
    (CDATA.tables || []).forEach(function (t) { push(t.name); });
    return out;
  }
  (CDATA.tables || []).forEach(function (t) { push(t.name); });
  (CDATA.keywords || []).forEach(push);
  return out;
}
function __testCompletion(text) {
  return JSON.stringify(__completionFor(text, __CDATA));
}
var __completionProvider = null;
function __setCompletionData(data) {
  __CDATA = data || { keywords: [], tables: [], columns: {} };
  if (!__editor || !monaco) return;
  if (__completionProvider) return;
  var trigger = [' ', '(', ',', '.', '=', '<', '>'];
  __completionProvider = monaco.languages.registerCompletionItemProvider('sql', {
    triggerCharacters: trigger,
    provideCompletionItems: function (model, position) {
      var word = model.getWordUntilPosition(position);
      var span = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber,
                    startColumn: word.startColumn, endColumn: word.endColumn };
      var cursorText = model.getValueInRange({
        startLineNumber: 1, startColumn: 1,
        endLineNumber: position.lineNumber, endColumn: position.column
      });
      // 去掉当前未完成单词，但保留 `表.` / `schema.`，否则上下文会丢失。
      var text = cursorText.replace(/[A-Za-z_][A-Za-z0-9_]*$/, '');
      var labels = __completionFor(text, __CDATA);
      // 推断 kind：优先看作 Field（列），否则按表/关键字；这里统一 Keyword/Class 混合简化为 Field
      var kind = monaco.languages.CompletionItemKind.Field;
      var sugg = labels.map(function (label) {
        return { label: label, kind: kind, insertText: label, range: span };
      });
      return { suggestions: sugg };
    }
  });
}
</script>
</body></html>
"""


class _Bridge(QObject):
    """Python↔JS 桥：JS 侧通知文本和选区变化。"""

    textChanged = Signal()
    selectionChanged = Signal(bool, str)

    @Slot()
    def emitChanged(self) -> None:  # pragma: no cover
        self.textChanged.emit()

    @Slot(bool, str)
    def emitSelectionChanged(self, selected: bool, text: str) -> None:  # pragma: no cover
        self.selectionChanged.emit(selected, text or "")


class MonacoEditorWidget(QWidget):
    """单标签 SQL 编辑器（monaco 内核）。"""

    textChanged = Signal()
    selectionChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._completion_data: dict = {"keywords": [], "tables": [], "columns": {}}
        self._cached_text = ""
        self._ready_flag = False
        self._selection_state = False
        self._selected_text = ""
        self._bridge = _Bridge()
        self._bridge.textChanged.connect(self.textChanged)
        self._bridge.selectionChanged.connect(self._on_selection_changed)

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
            self._poll_editor_ready(0)

    def _poll_editor_ready(self, attempt: int) -> None:
        """等待 Monaco 的 AMD 异步初始化完成，避免首次检查过早永久判定未就绪。"""
        self._view.page().runJavaScript(
            "(function(){ return !!window.__ready && !!window.__editor; })()",
            0, lambda ready: self._after_editor_ready(ready, attempt))

    def _after_editor_ready(self, has_editor, attempt: int = 0) -> None:
        if not has_editor and attempt < 100:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(50, lambda: self._poll_editor_ready(attempt + 1))
            return
        self._ready_flag = bool(has_editor)
        self._sync_words()


    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._view.url().isValid():
            self.load()

    # ---- 文本写入 ----
    def setPlainText(self, text: str) -> None:
        self._cached_text = text or ""
        if self._selection_state:
            self._selection_state = False
            self._selected_text = ""
            self.selectionChanged.emit(False)
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
        selected = self.selected_text()
        if selected is not None:
            return selected
        if self._ready():
            offset = self._evaluate("__getCursorOffset()", 0)
            return statement_at_cursor(self.text(), int(offset or 0))
        return statement_at_cursor(self._cached_text, 0) if self._cached_text else None

    def selected_text(self) -> str | None:
        """从 Monaco 当前选区读取可执行文本；没有非空选区时返回 None。"""
        if self._selection_state:
            return self._selected_text.strip() or None
        if self._ready():
            sel = self._evaluate("__getSelection()", None)
            if sel:
                start, end = int(sel[0]), int(sel[1])
                text = self.text()
                return text[start:end].strip() or None
        return None

    def has_selection(self) -> bool:
        """当前是否框选了非空文本。"""
        return self._selection_state

    def _on_selection_changed(self, selected: bool, text: str = "") -> None:
        selected = bool(selected)
        self._selected_text = (text or "") if selected else ""
        if selected != self._selection_state:
            self._selection_state = selected
            self.selectionChanged.emit(selected)

    def statements(self) -> list[str]:
        return split_sql_statements(self.text())

    # ---- 补全 ----
    def set_completion_words(self, words: list[str]) -> None:
        # 兼容旧接口：仅传入关键字词表
        self._completion_data = {
            "keywords": list(words or []),
            "tables": [],
            "columns": {},
        }
        self._sync_words()

    def set_completion_data(self, data: dict) -> None:
        """上下文感知补全数据：{keywords, tables:[{name,kind}], columns:{table:[col,...]}}。"""
        self._completion_data = {
            "keywords": list(data.get("keywords", []) or []),
            "tables": list(data.get("tables", []) or []),
            "columns": dict(data.get("columns", {}) or {}),
        }
        self._sync_words()

    def _sync_words(self) -> None:
        if not self._ready():
            return
        self._view.page().runJavaScript(
            f"__setCompletionData({json.dumps(self._completion_data)})", 0)

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
