# 打包 MagicCat（M7）：
#   java-bridge jar -> jlink 内嵌 JRE + 驱动/桥 jar -> PyInstaller(JPype) -> dist\MagicCat\
# 用法：.\scripts\build_package.ps1          # 全量
#       .\scripts\build_package.ps1 -SkipJlink  # 跳过 jlink（复用已有 runtime）
# 产出验证：.\dist\MagicCat\MagicCat.exe --selftest
param(
    [switch]$SkipJlink
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $root "java-bridge\target"
$stage = Join-Path $root "packaging\stage\jvm"
$pyi = Join-Path $root ".venv\Scripts\pyinstaller.exe"

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
        --strip-debug --no-header-files --no-man-pages
    if ($LASTEXITCODE -ne 0) { throw "jlink 失败 (exit $LASTEXITCODE)" }
} else {
    Write-Host "==> 2/3) 复用现有 jvm 资源（刷新 jar，保留 runtime）"
    New-Item -ItemType Directory -Path (Join-Path $stage "lib") -Force | Out-Null
    Copy-Item (Get-ChildItem $bridge -Filter "magiccat-bridge-*.jar" | Select-Object -First 1).FullName $stage -Force
    Copy-Item (Join-Path $bridge "lib\*.jar") (Join-Path $stage "lib") -Force
}

Write-Host "==> 4) PyInstaller 打包"
& $pyi --noconfirm --clean `
    --name MagicCat `
    --console `
    --paths $root `
    --collect-all jpype `
    --add-data "$stage;jvm" `
    (Join-Path $root "packaging\magiccat_main.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败 (exit $LASTEXITCODE)" }

Write-Host "==> 完成：$root\dist\MagicCat\MagicCat.exe"
Write-Host "   验证： .\dist\MagicCat\MagicCat.exe --selftest"
