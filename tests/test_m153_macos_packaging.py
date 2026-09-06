"""M153 回归：JVM 动态库路径按运行平台选择。"""

from __future__ import annotations


def test_macos_bundled_jre_path(tmp_path, monkeypatch) -> None:
    from magiccat.bridge import jvm

    bridge_dir = tmp_path / "jvm"
    (bridge_dir / "runtime" / "lib" / "server").mkdir(parents=True)
    (bridge_dir / "runtime" / "lib" / "server" / "libjvm.dylib").write_bytes(b"")
    monkeypatch.setattr(jvm.sys, "platform", "darwin")
    monkeypatch.setattr(jvm, "_resolve_bridge_dir", lambda: bridge_dir)

    assert jvm.bundled_jre() == bridge_dir / "runtime"
    assert jvm._jvm_library_relative_path().as_posix() == "lib/server/libjvm.dylib"


def test_windows_bundled_jre_path_is_preserved(tmp_path, monkeypatch) -> None:
    from magiccat.bridge import jvm

    bridge_dir = tmp_path / "jvm"
    (bridge_dir / "runtime" / "bin" / "server").mkdir(parents=True)
    (bridge_dir / "runtime" / "bin" / "server" / "jvm.dll").write_bytes(b"")
    monkeypatch.setattr(jvm.sys, "platform", "win32")
    monkeypatch.setattr(jvm, "_resolve_bridge_dir", lambda: bridge_dir)

    assert jvm.bundled_jre() == bridge_dir / "runtime"
    assert jvm._jvm_library_relative_path().as_posix() == "bin/server/jvm.dll"
