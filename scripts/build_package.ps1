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
$resolveUpx = Join-Path $root "scripts\resolve_upx.ps1"
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
$webviewLib = (& $python -c "from importlib.metadata import distribution; print(distribution('pywebview').locate_file('webview/lib'))" | Select-Object -First 1).Trim()
$webviewCore = Join-Path $webviewLib "Microsoft.Web.WebView2.Core.dll"
$webviewForms = Join-Path $webviewLib "Microsoft.Web.WebView2.WinForms.dll"
$webviewLoader = Join-Path $webviewLib "runtimes\win-x64\native\WebView2Loader.dll"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $webviewCore) -or
    -not (Test-Path -LiteralPath $webviewForms) -or -not (Test-Path -LiteralPath $webviewLoader)) {
    throw "无法定位 pywebview 的 WebView2 程序集：$webviewLib"
}
$webviewCoreData = "$webviewCore;webview/lib"
$webviewFormsData = "$webviewForms;webview/lib"
$webviewLoaderBinary = "$webviewLoader;webview/lib/runtimes/win-x64/native"
Write-Host "    WebView2 程序集：$webviewLib"
& $pyi --noconfirm --clean `
    --noupx `
    --name MagicCat `
    $pyiMode `
    --distpath $distDir `
    --workpath $workDir `
    --specpath $workDir `
    --paths $root `
    --additional-hooks-dir $hookDir `
    --icon (Join-Path $root "magiccat\resources\app_icon.ico") `
    --collect-all jpype `
    --exclude-module magiccat.ui.monaco_editor_qt `
    --exclude-module ssl `
    --exclude-module _ssl `
    --exclude-module _hashlib `
    --add-data $webviewCoreData `
    --add-data $webviewFormsData `
    --add-binary $webviewLoaderBinary `
    --add-data "$stage;jvm" `
    --add-data (Join-Path $root "magiccat\resources;magiccat\resources") `
    (Join-Path $root "packaging\magiccat_main.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败 (exit $LASTEXITCODE)" }

if ($Windowed) {
    Write-Host "==> 5) 白名单压缩 Python/PySide 二进制"
    $upx = (& $resolveUpx | Select-Object -Last 1).Trim()
    $internal = Join-Path $distDir "MagicCat\_internal"
    $upxTargets = @(
        (Join-Path $internal "python312.dll"),
        (Join-Path $internal "sqlite3.dll")
    )
    $upxTargets += (Get-ChildItem -LiteralPath $internal -File -Filter "*.pyd").FullName
    $upxTargets += (Get-ChildItem -LiteralPath (Join-Path $internal "PySide6") -File -Filter "*.pyd").FullName
    $upxTargets += (Get-ChildItem -LiteralPath (Join-Path $internal "shiboken6") -File -Filter "*.pyd").FullName
    foreach ($target in ($upxTargets | Sort-Object -Unique)) {
        $upxOutput = & $upx --best --lzma -qq -- $target 2>&1
        if ($LASTEXITCODE -ne 0) { throw "UPX 压缩失败：$target`n$upxOutput" }
    }
    $releaseBytes = (Get-ChildItem (Join-Path $distDir "MagicCat") -Recurse -File |
        Measure-Object -Property Length -Sum).Sum
    $releaseMb = [math]::Round($releaseBytes / 1MB, 2)
    Write-Host "    应用目录：${releaseMb} MB（JRE、Qt DLL、插件与翻译包保持原样）"
    if ($releaseBytes -gt 100MB) {
        throw "Windows 正式应用超过 100 MB：${releaseMb} MB"
    }
}

Write-Host "==> 完成：$root\dist\MagicCat\MagicCat.exe"
