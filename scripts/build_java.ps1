# 构建 java-bridge：产出 target/magiccat-bridge-<version>.jar + target/lib/（运行时依赖）
param(
    [switch]$Clean
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bridgeDir = Join-Path $root "java-bridge"

Push-Location $bridgeDir
try {
    if ($Clean) {
        Write-Host "==> mvn clean"
        mvn -q clean
    }
    Write-Host "==> mvn package"
    mvn -q package
    if ($LASTEXITCODE -ne 0) { throw "Maven 构建失败 (exit $LASTEXITCODE)" }
    Write-Host "==> 构建完成："
    Get-ChildItem (Join-Path $bridgeDir "target") -Filter "magiccat-bridge-*.jar" | Select-Object -ExpandProperty FullName
    Write-Host "    lib: $(Get-ChildItem (Join-Path $bridgeDir 'target\lib') -Filter '*.jar' | Measure-Object | Select-Object -ExpandProperty Count) 个依赖 jar"
}
finally {
    Pop-Location
}
