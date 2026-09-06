# Windows 完整发行构建：Java bridge -> PyInstaller(windowed) -> selftest -> 便携 ZIP -> Inno Setup 安装器
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

Write-Host "==> 1) 强制重建 java-bridge"
Invoke-Step -FilePath $buildJava -Arguments @()

Write-Host "==> 2) 重建 PyInstaller 应用"
$packageParameters = @{ Windowed = $true }
if ($SkipJlink) { $packageParameters.SkipJlink = $true }
& $buildPackage @packageParameters
if ($LASTEXITCODE -ne 0) {
    throw "构建步骤失败：$buildPackage (exit $LASTEXITCODE)"
}

if (-not (Test-Path -LiteralPath $exe)) {
    throw "PyInstaller 产物不存在：$exe"
}

Write-Host "==> 3) 执行打包自检"
$selftestOutput = Join-Path ([System.IO.Path]::GetTempPath()) "magiccat-selftest-$PID.json"
$previousSelftestOutput = $env:MAGICCAT_SELFTEST_OUTPUT
try {
    $env:MAGICCAT_SELFTEST_OUTPUT = $selftestOutput
    # windowed 子系统不会让 PowerShell 的直接调用可靠等待进程结束。
    $selftestProcess = Start-Process -FilePath $exe -ArgumentList @("--selftest") -Wait -PassThru -WindowStyle Hidden
    $selftestExit = $selftestProcess.ExitCode
    if ($selftestExit -ne 0) {
        throw "打包自检失败 (exit $selftestExit)"
    }
    if (-not (Test-Path -LiteralPath $selftestOutput)) {
        throw "打包自检未生成结果文件：$selftestOutput"
    }
    Write-Host ("    结果：" + (Get-Content -LiteralPath $selftestOutput -Raw).Trim())
}
finally {
    if (Test-Path -LiteralPath $selftestOutput) {
        Remove-Item -LiteralPath $selftestOutput -Force
    }
    if ($null -eq $previousSelftestOutput) {
        Remove-Item Env:MAGICCAT_SELFTEST_OUTPUT -ErrorAction SilentlyContinue
    } else {
        $env:MAGICCAT_SELFTEST_OUTPUT = $previousSelftestOutput
    }
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
