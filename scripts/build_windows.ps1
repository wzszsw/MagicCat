# Windows 完整发行构建：Java bridge -> PyInstaller(windowed) -> 便携 ZIP -> Inno Setup 安装器
# 每次运行都会重新构建 Java bridge 和应用本体，避免把旧 dist 目录直接编译成安装器。
# 用法：
#   .\scripts\build_windows.ps1
#   .\scripts\build_windows.ps1 -SkipJlink  # 复用已有内嵌 JRE，加快重复构建
param(
    [switch]$SkipJlink
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$buildJava = Join-Path $root "scripts\build_java.ps1"
$buildPackage = Join-Path $root "scripts\build_package.ps1"
$buildRelease = Join-Path $root "scripts\build_release.ps1"
$iss = Join-Path $root "packaging\MagicCat.iss"
$exe = Join-Path $root "dist\MagicCat\MagicCat.exe"
$stage = Join-Path $root "packaging\stage\jvm"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "构建步骤失败：$FilePath (exit $LASTEXITCODE)"
    }
}

Write-Host "==> 1) 清理旧的正式发行产物"
if (-not $SkipJlink -and (Test-Path -LiteralPath $stage)) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
foreach ($path in @(
    (Join-Path $root "dist\MagicCat"),
    (Join-Path $root "dist\installer"),
    (Join-Path $root "build\MagicCat")
)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

Write-Host "==> 2) 强制重建 java-bridge（mvn clean package）"
Invoke-Step -FilePath $buildJava -Arguments @("-Clean")

Write-Host "==> 3) 重建 PyInstaller 应用"
$packageParameters = @{ Windowed = $true; Clean = $true }
if ($SkipJlink) { $packageParameters.SkipJlink = $true }
& $buildPackage @packageParameters
if ($LASTEXITCODE -ne 0) {
    throw "构建步骤失败：$buildPackage (exit $LASTEXITCODE)"
}

if (-not (Test-Path -LiteralPath $exe)) {
    throw "PyInstaller 产物不存在：$exe"
}

Write-Host "==> 4) 生成便携版 ZIP"
Invoke-Step -FilePath $buildRelease -Arguments @()

Write-Host "==> 5) 查找 Inno Setup 编译器"
$isccCandidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
    (Join-Path ${env:ProgramFiles} "Inno Setup 7\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe"),
    (Join-Path ${env:ProgramFiles} "Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$iscc = $isccCandidates | Select-Object -First 1
if (-not $iscc) {
    throw "未找到 Inno Setup ISCC.exe，请安装 Inno Setup 7 或将 ISCC.exe 加入 PATH"
}

Write-Host "    编译器：$iscc"
Invoke-Step -FilePath $iscc -Arguments @($iss)

$versionMatch = Select-String -Path (Join-Path $root "magiccat\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
$version = if ($versionMatch) { $versionMatch.Matches.Groups[1].Value } else { "0.1.0" }
$installer = Join-Path $root "dist\installer\MagicCat-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "安装器产物不存在：$installer"
}

$installerInfo = Get-Item -LiteralPath $installer
$sizeMb = [math]::Round($installerInfo.Length / 1MB, 2)
Write-Host "==> 完成：$installer（约 ${sizeMb} MB）"
