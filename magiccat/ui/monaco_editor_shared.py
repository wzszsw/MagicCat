"""Monaco page source shared by the WebView2 and Qt fallback backends."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

_HTML_SOURCE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html, body, #container { height: 100%; margin: 0; padding: 0; }
</style></head><body><div id="container"></div>
<script src="__LOADER__"></script><script>
require.config({ paths: { 'vs': '__VS__' } });
var __bridge = null, __editor = null;
function __sendBridge(method, args) {
  if (window.chrome && window.chrome.webview) {
    window.chrome.webview.postMessage(JSON.stringify({method: method, args: args || []}));
  } else if (__bridge && __bridge[method]) { __bridge[method].apply(__bridge, args || []); }
}
function __emitSelectionState() {
  if (!__editor) return;
  var selection = __editor.getSelection();
  var selected = !!selection && !selection.isEmpty();
  var text = selected ? __editor.getModel().getValueInRange(selection) : '';
  if (window.chrome && window.chrome.webview) __sendBridge('emitSelectionChanged', [selected, text]);
  else if (__bridge) __bridge.emitSelectionChanged(selected, text);
}
if (!(window.chrome && window.chrome.webview)) {
  var __channelScript = document.createElement('script');
  __channelScript.src = 'qrc:///qtwebchannel/qwebchannel.js';
  __channelScript.onload = function () { new QWebChannel(qt.webChannelTransport, function (channel) {
    __bridge = channel.objects.bridge; __emitSelectionState();
  }); };
  document.head.appendChild(__channelScript);
}
require(['vs/editor/editor.main', 'vs/basic-languages/sql/sql'], function () {
  __editor = monaco.editor.create(document.getElementById('container'), {
    value: '', language: 'sql', theme: 'vs', automaticLayout: true,
    minimap: { enabled: false }, scrollBeyondLastLine: false
  });
  __editor.onDidChangeModelContent(function () {
    if (window.chrome && window.chrome.webview) __sendBridge('emitChanged');
    else if (__bridge) __bridge.emitChanged();
  });
  __editor.onDidChangeCursorSelection(function () { __emitSelectionState(); });
  __emitSelectionState(); window.__ready = true;
});
function __setValue(v) { if (__editor) __editor.setValue(v || ''); }
function __getValue() { return __editor ? __editor.getValue() : ''; }
function __getCursorOffset() { return __editor ? __editor.getModel().getOffsetAt(__editor.getPosition()) : 0; }
function __getSelection() {
  if (!__editor) return null;
  var s = __editor.getSelection(); if (!s || s.isEmpty()) return null;
  var m = __editor.getModel(); return [m.getOffsetAt(s.getStartPosition()), m.getOffsetAt(s.getEndPosition())];
}
var __CDATA = { keywords: [], tables: [], columns: {} };
function __completionFor(text, data) {
  var CDATA = data || __CDATA;
  var TABLE_CTX = ['FROM','JOIN','INTO','UPDATE','TABLE','REFERENCES','DELETE'];
  var COL_CTX = ['SELECT','WHERE','ON','HAVING','AND','OR','BY','GROUP','ORDER','SET'];
  var up = (text || '').toUpperCase(), out = [];
  function push(label) { if (out.indexOf(label) < 0) out.push(label); }
  var dotM = (text || '').match(/([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)?$/);
  if (dotM) {
    var beforeDot = (text || '').slice(0, dotM.index);
    if (/\b(FROM|JOIN|INTO|UPDATE|TABLE|REFERENCES)\s+[^;]*$/i.test(beforeDot)) {
      var tablePrefix = (dotM[2] || '').toLowerCase();
      (CDATA.tables || []).forEach(function (t) { if (!tablePrefix || String(t.name).toLowerCase().indexOf(tablePrefix) === 0) push(t.name); });
      return out;
    }
    var sourceName = dotM[1];
    var aliasMatch = (text || '').match(/\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)[^;]*$/i);
    var tableName = aliasMatch && aliasMatch[2].toLowerCase() === sourceName.toLowerCase() ? aliasMatch[1] : sourceName;
    var columnList = CDATA.columns[sourceName] || CDATA.columns[sourceName.toLowerCase()] || CDATA.columns[tableName] || CDATA.columns[tableName.toLowerCase()] || [];
    var prefix = (dotM[2] || '').toLowerCase();
    columnList.forEach(function (column) { if (!prefix || String(column).toLowerCase().indexOf(prefix) === 0) push(column); });
    return out;
  }
  var lkM = up.match(/(\b[A-Z]+)\s*$/), lk = lkM ? lkM[1] : '';
  var tableCtxM = up.match(/\b(FROM|JOIN|INTO|UPDATE|TABLE|REFERENCES|DELETE)\s+([A-Z0-9_]*)$/);
  if (tableCtxM) {
    var tablePrefix2 = tableCtxM[2].toLowerCase();
    (CDATA.tables || []).forEach(function (t) { if (!tablePrefix2 || String(t.name).toLowerCase().indexOf(tablePrefix2) === 0) push(t.name); });
    return out;
  }
  if (COL_CTX.indexOf(lk) >= 0) {
    var seen = {};
    (CDATA.tables || []).forEach(function (t) { (CDATA.columns[t.name] || []).forEach(function (c) { if (!seen[c]) { seen[c] = 1; push(c); } }); });
    (CDATA.tables || []).forEach(function (t) { push(t.name); }); return out;
  }
  (CDATA.tables || []).forEach(function (t) { push(t.name); });
  (CDATA.keywords || []).forEach(push); return out;
}
function __testCompletion(text) { return JSON.stringify(__completionFor(text, __CDATA)); }
var __completionProvider = null;
function __setCompletionData(data) {
  __CDATA = data || { keywords: [], tables: [], columns: {} };
  if (!__editor || !monaco || __completionProvider) return;
  __completionProvider = monaco.languages.registerCompletionItemProvider('sql', {
    triggerCharacters: [' ', '(', ',', '.', '=', '<', '>'],
    provideCompletionItems: function (model, position) {
      var word = model.getWordUntilPosition(position);
      var span = { startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn };
      var cursorText = model.getValueInRange({ startLineNumber: 1, startColumn: 1, endLineNumber: position.lineNumber, endColumn: position.column });
      var text = cursorText.replace(/[A-Za-z_][A-Za-z0-9_]*$/, '');
      return { suggestions: __completionFor(text, __CDATA).map(function (label) {
        return { label: label, kind: monaco.languages.CompletionItemKind.Field, insertText: label, range: span };
      }) };
    }
  });
}
</script></body></html>"""


class _Bridge(QObject):
    textChanged = Signal()
    selectionChanged = Signal(bool, str)

    @Slot()
    def emitChanged(self) -> None:  # pragma: no cover
        self.textChanged.emit()

    @Slot(bool, str)
    def emitSelectionChanged(self, selected: bool, text: str) -> None:  # pragma: no cover
        self.selectionChanged.emit(selected, text or "")
