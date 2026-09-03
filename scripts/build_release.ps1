# 生成便携版发行包：dist\MagicCat\ -> dist\MagicCat-<版本>-portable.zip
# 依赖已构建的 dist\MagicCat\（若缺失或加 -Rebuild 会先执行 build_package.ps1）
param(
    [switch]$Rebuild
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pkgDir = Join-Path $root "dist\MagicCat"
$stage = Join-Path $root "packaging\stage\jvm"

if ($Rebuild -or -not (Test-Path (Join-Path $pkgDir "MagicCat.exe"))) {
    Write-Host "==> 先打包（dist\MagicCat）"
    if (Test-Path (Join-Path $stage "runtime\bin\server\jvm.dll")) {
        & (Join-Path $root "scripts\build_package.ps1") -SkipJlink
    } else {
        & (Join-Path $root "scripts\build_package.ps1")
    }
}

$ver = (Select-String -Path (Join-Path $root "magiccat\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"').Matches.Groups[1].Value
if (-not $ver) { $ver = "0.1.0" }
$zip = Join-Path $root "dist\MagicCat-$ver-portable.zip"

Write-Host "==> 压缩便携版 -> $zip"
Compress-Archive -Path (Join-Path $pkgDir "*") -DestinationPath $zip -Force

Write-Host "==> 校验关键文件存在："
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
    $names = $archive.Entries.FullName
    foreach ($need in @("MagicCat.exe", "_internal/jvm/magiccat-bridge-0.1.0.jar",
                        "_internal/jvm/runtime/bin/server/jvm.dll",
                        "_internal/magiccat/resources/app_icon.ico")) {
        $hit = $names -contains $need
        Write-Host ("   {0,-55} {1}" -f $need, ($(if ($hit) { "OK" } else { "缺失!" })))
        if (-not $hit) { throw "zip 缺文件: $need" }
    }
}
finally {
    $archive.Dispose()
}
$size = [math]::Round((Get-Item $zip).Length / 1MB)
Write-Host "==> 完成：$zip（约 ${size} MB）"
