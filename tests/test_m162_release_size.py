"""M162 bounded Windows binary compression regressions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_upx_download_is_pinned_and_verified():
    script = (ROOT / "scripts" / "resolve_upx.ps1").read_text(encoding="utf-8")

    assert '$version = "5.2.1"' in script
    assert "EABC6792A347D45E945BE7748423E7868FD01B0D2BCAA2F4B1031FD71FF69BDA" in script
    assert "Get-FileHash" in script


def test_release_uses_upx_allowlist_without_touching_jre_or_qt_dlls():
    script = (ROOT / "scripts" / "build_package.ps1").read_text(encoding="utf-8")
    compression = script.split('Write-Host "==> 5) 白名单压缩', maxsplit=1)[1]

    assert "--noupx" in script
    assert 'Join-Path $internal "python312.dll"' in compression
    assert 'Join-Path $internal "sqlite3.dll"' in compression
    assert '-Filter "*.pyd"' in compression
    assert "jvm.dll" not in compression
    assert "Qt6Core.dll" not in compression
    assert "100MB" in compression


def test_webview2_loader_does_not_import_pywebview_runtime_stack():
    source = (ROOT / "magiccat" / "ui" / "webview2_editor.py").read_text(encoding="utf-8")

    assert 'import_module("webview.platforms.edgechromium")' not in source
    assert 'distribution("pywebview")' in source
    assert "Microsoft.Web.WebView2.Core.dll" in source
