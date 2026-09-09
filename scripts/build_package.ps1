# 打包 MagicCat（M7）：
#   java-bridge jar -> jlink 内嵌 JRE + 驱动/桥 jar -> PyInstaller(JPype) -> dist\MagicCat\
# 用法：.\scripts\build_package.ps1                    # 调试版（带控制台）
#       .\scripts\build_package.ps1 -Windowed          # 发布版（无控制台）
#       .\scripts\build_package.ps1 -SkipJlink         # 跳过 jlink（复用已有 runtime）
#       .\scripts\build_package.ps1 -Windowed -SkipJlink
param(
    [switch]$SkipJlink,
    [switch]$Windowed,
    [switch]$Clean
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $root "java-bridge\target"
$stage = Join-Path $root "packaging\stage\jvm"
$hookDir = Join-Path $root "packaging\pyinstaller_hooks"
$pyi = Join-Path $root ".venv\Scripts\pyinstaller.exe"
$python = Join-Path $root ".venv\Scripts\python.exe"
$distDir = Join-Path $root "dist"
$workDir = Join-Path $root "build\MagicCat"

if ($Clean) {
    Write-Host "==> 清理旧的 bridge stage、PyInstaller 输出和工作目录"
    if (-not $SkipJlink -and (Test-Path -LiteralPath $stage)) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
    foreach ($path in @(
        (Join-Path $distDir "MagicCat"),
        $workDir
    )) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

Write-Host "==> 1) 确保 java-bridge 已构建"
if (-not (Get-ChildItem $bridge -Filter "magiccat-bridge-*.jar" -ErrorAction SilentlyContinue)) {
    & (Join-Path $root "scripts\build_java.ps1")
}

Write-Host "==> 2) 组装 jvm 资源目录 ($stage)"
$runtimeOk = Test-Path (Join-Path $stage "runtime\bin\server\jvm.dll")
if (-not $SkipJlink -and -not $runtimeOk) {
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    New-Item -ItemType Directory -Path $stage | Out-Null
    Copy-Item (Get-ChildItem $bridge -Filter "magiccat-bridge-*.jar" | Select-Object -First 1).FullName $stage
    New-Item -ItemType Directory -Path (Join-Path $stage "lib") | Out-Null
    Copy-Item (Join-Path $bridge "lib\*.jar") (Join-Path $stage "lib")

    if (-not $env:JAVA_HOME) { throw "JAVA_HOME 未设置，无法 jlink" }
    Write-Host "==> 3) jlink 内嵌 JRE（裁剪 Java 17）"
    & (Join-Path $env:JAVA_HOME "bin\jlink.exe") `
        --add-modules java.base,java.sql,java.naming,java.management,jdk.unsupported `
        --output (Join-Path $stage "runtime") `
        --strip-debug --no-header-files --no-man-pages --compress=2
    if ($LASTEXITCODE -ne 0) { throw "jlink 失败 (exit $LASTEXITCODE)" }
} else {
    Write-Host "==> 2/3) 复用现有 jvm 资源（刷新 jar，保留 runtime）"
    New-Item -ItemType Directory -Path (Join-Path $stage "lib") -Force | Out-Null
    Copy-Item (Get-ChildItem $bridge -Filter "magiccat-bridge-*.jar" | Select-Object -First 1).FullName $stage -Force
    Copy-Item (Join-Path $bridge "lib\*.jar") (Join-Path $stage "lib") -Force
}

Write-Host "==> 4) PyInstaller 打包"
$pyiMode = if ($Windowed) { "--windowed" } else { "--console" }
Write-Host "    模式：$pyiMode"
$pythonDllDir = (& $python -c "import sys; print(sys.base_prefix + r'\DLLs')" | Select-Object -First 1).Trim()
$pythonSsl = Join-Path $pythonDllDir "libssl-3-x64.dll"
$pythonCrypto = Join-Path $pythonDllDir "libcrypto-3-x64.dll"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $pythonDllDir "_ssl.pyd")) -or
    -not (Test-Path -LiteralPath $pythonSsl) -or -not (Test-Path -LiteralPath $pythonCrypto)) {
    throw "无法定位 uv Python 的 DLL 目录：$pythonDllDir"
}
$pythonSslBinary = "$pythonSsl;."
$pythonCryptoBinary = "$pythonCrypto;."
Write-Host "    Python DLL：$pythonDllDir"
# PyInstaller may otherwise resolve these names from PostgreSQL on PATH.
# Python's _ssl.pyd must use the matching OpenSSL build from this interpreter.
& $pyi --noconfirm --clean `
    --name MagicCat `
    $pyiMode `
    --distpath $distDir `
    --workpath $workDir `
    --specpath $workDir `
    --paths $root `
    --additional-hooks-dir $hookDir `
    --icon (Join-Path $root "magiccat\resources\app_icon.ico") `
    --collect-all jpype `
    --hidden-import webview.platforms.edgechromium `
    --exclude-module magiccat.ui.monaco_editor_qt `
    --exclude-module webview.platforms.android `
    --exclude-module webview.platforms.cef `
    --exclude-module webview.platforms.cocoa `
    --exclude-module webview.platforms.gtk `
    --exclude-module webview.platforms.mshtml `
    --exclude-module webview.platforms.qt `
    --exclude-module webview.platforms.win32 `
    --exclude-module webview.platforms.winforms `
    --add-binary $pythonCryptoBinary `
    --add-binary $pythonSslBinary `
    --add-data "$stage;jvm" `
    --add-data (Join-Path $root "magiccat\resources;magiccat\resources") `
    (Join-Path $root "packaging\magiccat_main.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败 (exit $LASTEXITCODE)" }

Write-Host "==> 完成：$root\dist\MagicCat\MagicCat.exe"
