#!/usr/bin/env bash
# 构建 Apple Silicon macOS 正式发行包：Java bridge -> jlink -> PyInstaller(.app) -> DMG。
# 该脚本故意每次清理目标目录，避免把旧 dist 内容带进 DMG。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="arm64"
OUT_DIR="$ROOT/dist"

usage() {
    cat <<'EOF'
用法：scripts/build_macos.sh [--arch arm64] [--output-dir DIR]

当前发行目标仅支持 Apple Silicon arm64；x86_64 请使用 macOS Intel runner 扩展脚本后再启用。
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --arch)
            [[ $# -ge 2 ]] || { usage >&2; exit 2; }
            ARCH="$2"
            shift 2
            ;;
        --output-dir)
            [[ $# -ge 2 ]] || { usage >&2; exit 2; }
            OUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "此脚本只能在 macOS 上运行。" >&2
    exit 1
fi
if [[ "$ARCH" != "arm64" ]]; then
    echo "当前只支持 --arch arm64，收到：$ARCH" >&2
    exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
    echo "当前构建目标是 Apple Silicon，runner 架构必须为 arm64。" >&2
    exit 1
fi

JAVA_HOME="${JAVA_HOME:-}"
if [[ -z "$JAVA_HOME" || ! -x "$JAVA_HOME/bin/jlink" ]]; then
    echo "JAVA_HOME 未指向包含 jlink 的 JDK 17，请先配置 Java 17。" >&2
    exit 1
fi

UV_BIN="${UV_BIN:-uv}"
MAVEN_BIN="${MAVEN_BIN:-mvn}"
BRIDGE_DIR="$ROOT/java-bridge/target"
STAGE="$ROOT/packaging/stage/jvm"
DIST_DIR="$OUT_DIR"
APP="$DIST_DIR/MagicCat.app"
WORK_DIR="$ROOT/build/macos"
VERSION="$(PYTHONPATH="$ROOT" python3 -c 'from magiccat import __version__; print(__version__)')"
DMG="$OUT_DIR/MagicCat-$VERSION-macos-$ARCH.dmg"
ICON_TMP="$(mktemp -d "${TMPDIR:-/tmp}/magiccat-icon.XXXXXX")"
trap 'rm -rf "$ICON_TMP"' EXIT

echo "==> 清理旧的 macOS 构建目录"
rm -rf "$STAGE" "$APP" "$DMG" "$WORK_DIR"
mkdir -p "$STAGE/lib" "$DIST_DIR" "$WORK_DIR"

echo "==> 1) 构建 java-bridge"
"$MAVEN_BIN" -q -f "$ROOT/java-bridge/pom.xml" package
BRIDGE_JAR="$(find "$BRIDGE_DIR" -maxdepth 1 -type f -name 'magiccat-bridge-*.jar' -print -quit)"
if [[ -z "$BRIDGE_JAR" ]]; then
    echo "未找到 Java bridge jar。" >&2
    exit 1
fi
cp "$BRIDGE_JAR" "$STAGE/"
cp "$BRIDGE_DIR/lib/"*.jar "$STAGE/lib/"

echo "==> 2) 使用 Java 17 jlink 生成 arm64 内嵌 JRE"
"$JAVA_HOME/bin/jlink" \
    --add-modules java.base,java.sql,java.naming,java.management,jdk.unsupported \
    --output "$STAGE/runtime" \
    --strip-debug --no-header-files --no-man-pages

echo "==> 3) 生成 macOS 应用图标"
ICONSET="$ICON_TMP/MagicCat.iconset"
mkdir -p "$ICONSET"
PNG="$ROOT/magiccat/resources/app_icon.png"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    doubled=$((size * 2))
    sips -z "$doubled" "$doubled" "$PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$ICON_TMP/MagicCat.icns"

echo "==> 4) PyInstaller 构建 windowed .app"
"$UV_BIN" run pyinstaller --noconfirm --clean \
    --name MagicCat \
    --windowed \
    --target-architecture arm64 \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    --specpath "$WORK_DIR" \
    --paths "$ROOT" \
    --icon "$ICON_TMP/MagicCat.icns" \
    --collect-all jpype \
    --add-data "$STAGE:jvm" \
    --add-data "$ROOT/magiccat/resources:magiccat/resources" \
    "$ROOT/packaging/magiccat_main.py"

if [[ ! -d "$APP" ]]; then
    echo "PyInstaller 未生成应用包：$APP" >&2
    exit 1
fi
JVM_LIB="$(find "$APP" -type f -name 'libjvm.dylib' -print -quit)"
if [[ -z "$JVM_LIB" ]]; then
    echo "应用包缺少内嵌 libjvm.dylib。" >&2
    exit 1
fi
RESOURCE_FILE="$(find "$APP" -type f -path '*/magiccat/resources/app_icon.png' -print -quit)"
if [[ -z "$RESOURCE_FILE" ]]; then
    echo "应用包缺少 MagicCat 资源目录。" >&2
    exit 1
fi

echo "==> 5) 生成 DMG"
hdiutil create -volname MagicCat -srcfolder "$APP" -ov -format UDZO "$DMG" >/dev/null
if [[ ! -f "$DMG" ]]; then
    echo "DMG 生成失败：$DMG" >&2
    exit 1
fi

size_mb="$(du -m "$DMG" | awk '{print $1}')"
echo "==> 完成：$DMG（约 ${size_mb} MB，arm64，未签名）"
