# Locate or download the pinned UPX build tool used by Windows release builds.
param()

$ErrorActionPreference = "Stop"
$version = "5.2.1"
$expectedSha256 = "EABC6792A347D45E945BE7748423E7868FD01B0D2BCAA2F4B1031FD71FF69BDA"
$downloadUrl = "https://github.com/upx/upx/releases/download/v$version/upx-$version-win64.zip"

if ($env:MAGICCAT_UPX) {
    $override = (Resolve-Path -LiteralPath $env:MAGICCAT_UPX).Path
    if (-not (Test-Path -LiteralPath $override -PathType Leaf)) {
        throw "MAGICCAT_UPX 未指向 upx.exe：$override"
    }
    Write-Output $override
    exit 0
}

$cacheRoot = Join-Path $env:LOCALAPPDATA "MagicCatBuildTools\upx-$version"
$upx = Join-Path $cacheRoot "upx-$version-win64\upx.exe"
if (Test-Path -LiteralPath $upx -PathType Leaf) {
    Write-Output $upx
    exit 0
}

New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
$archive = Join-Path $cacheRoot "upx-$version-win64.zip"
if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    Write-Host "==> 下载 UPX $version（Windows 发布构建工具）"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archive
}
$actualSha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
if ($actualSha256 -ne $expectedSha256) {
    throw "UPX 下载文件校验失败：期望 $expectedSha256，实际 $actualSha256"
}
Expand-Archive -LiteralPath $archive -DestinationPath $cacheRoot -Force
if (-not (Test-Path -LiteralPath $upx -PathType Leaf)) {
    throw "UPX 解压后未找到 upx.exe：$upx"
}
Write-Output $upx
