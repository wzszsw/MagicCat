"""JVM 生命周期管理（JPype）。

设计要点（见 docs/MagicCat设计方案.md §3）：
- JVM 必须在任何 Java 类被引用前一次性启动，且全局唯一；
- 所有 JDBC 逻辑收敛在 Java 侧 magiccat-bridge.jar，Python 只做门面调用；
- 未来若改独立桥接进程，只需替换本模块实现，不动上层。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 开发态：java-bridge/target/ 下由 Maven 产出的 jar（脚本 scripts/build_java.ps1）
_DEV_BRIDGE_DIR = Path(__file__).resolve().parents[2] / "java-bridge" / "target"

_PKG_BRIDGE_DIR_ENV = "MAGICCAT_BRIDGE_DIR"


def _frozen_base() -> Path:
    """PyInstaller 解包目录（onedir 下为 _internal，onefile 下为临时解包目录）。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(sys.executable).resolve().parent


def _resolve_bridge_dir() -> Path:
    env_dir = os.environ.get(_PKG_BRIDGE_DIR_ENV)
    if env_dir:
        return Path(env_dir)
    if getattr(sys, "frozen", False):
        return _frozen_base() / "jvm"
    return _DEV_BRIDGE_DIR


def bundled_jre() -> Path | None:
    """打包内嵌 JRE（jlink 产物）路径；未打包/未找到返回 None。"""
    candidate = _resolve_bridge_dir() / "runtime"
    if (candidate / "bin" / "server" / "jvm.dll").exists():
        return candidate
    return None


def discover_classpath(bridge_dir: Path | None = None) -> list[str]:
    """返回 [magiccat-bridge-*.jar, 依赖 lib/*.jar] 的 classpath 列表。"""
    d = Path(bridge_dir) if bridge_dir else _resolve_bridge_dir()
    bridge_jars = sorted(d.glob("magiccat-bridge-*.jar"))
    if not bridge_jars:
        raise FileNotFoundError(
            f"未找到 magiccat-bridge jar（{d}）。请先执行 scripts/build_java.ps1 构建 java-bridge。"
        )
    lib_jars = sorted((d / "lib").glob("*.jar"))
    return [str(p) for p in bridge_jars] + [str(p) for p in lib_jars]


class BridgeRuntime:
    """JPype JVM 运行时封装：start() / shutdown() / jclass()。"""

    def __init__(self, bridge_dir: Path | None = None) -> None:
        self._bridge_dir = Path(bridge_dir) if bridge_dir else _resolve_bridge_dir()
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def start(self, jvm_args: list[str] | None = None) -> None:
        import jpype

        if jpype.isJVMStarted():
            self._started = True
            return
        classpath = discover_classpath(self._bridge_dir)
        args = jvm_args or [
            "-Dfile.encoding=UTF-8",
            "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
        ]
        # 优先使用打包内嵌 JRE，其次允许 MAGICCAT_JAVA_HOME，最后交给 JPype 自动探测
        jvm_path = None
        jre = bundled_jre()
        if jre is not None:
            jvm_path = str(jre / "bin" / "server" / "jvm.dll")
        elif os.environ.get("MAGICCAT_JAVA_HOME"):
            jvm_path = str(Path(os.environ["MAGICCAT_JAVA_HOME"])
                           / "bin" / "server" / "jvm.dll")
        if jvm_path is None:
            jvm_path = jpype.getDefaultJVMPath()
        # JPype 从调用 Java 时释放 GIL；JVM 崩溃无法热重启 —— 由调用方兜底提示
        jpype.startJVM(jvm_path, *args, classpath=classpath, convertStrings=True)
        self._started = True

    def jclass(self, fqcn: str):
        """获取 Java 类。调用前必须先 start()。"""
        import jpype

        if not jpype.isJVMStarted():
            raise RuntimeError("JVM 尚未启动，请先调用 BridgeRuntime.start()")
        return jpype.JClass(fqcn)

    def shutdown(self) -> None:
        import jpype

        if jpype.isJVMStarted():
            jpype.shutdownJVM()
        self._started = False
