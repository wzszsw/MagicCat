# openGauss 本机联调容器助手（Windows + Podman）
#
# 默认只做可恢复操作：已有容器则启动，未找到才创建；不会删除容器或清理数据。
# 常用用法：
#   .\scripts\opengauss.ps1                         # 创建/启动并等待端口
#   .\scripts\opengauss.ps1 -Action status
#   .\scripts\opengauss.ps1 -Action logs
#   .\scripts\opengauss.ps1 -Action gsql
#   .\scripts\opengauss.ps1 -Action remove -Force   # 明确确认后删除容器

[CmdletBinding()]
param(
    [ValidateSet("up", "start", "stop", "restart", "status", "logs", "shell", "gsql", "remove")]
    [string]$Action = "up",
    [string]$ContainerName = "magiccat-opengauss",
    [string]$Image = "docker.io/library/opengauss:6.0.3",
    [int]$HostPort = 15432,
    [string]$GaussPassword = "Gaussdb@123",
    [int]$LogTail = 80,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command podman -ErrorAction SilentlyContinue)) {
    throw "未找到 podman，请先启动 Podman machine 并确认 podman 在 PATH 中。"
}

function Invoke-Podman {
    param([string[]]$Arguments)

    & podman @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "podman 命令失败（exit $LASTEXITCODE）：podman $($Arguments -join ' ')"
    }
}

function Test-Container {
    & podman container exists $ContainerName 2>$null
    return $LASTEXITCODE -eq 0
}

function Get-ContainerState {
    if (-not (Test-Container)) {
        return $null
    }
    $state = & podman inspect --format '{{.State.Status}}' $ContainerName 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return ($state | Select-Object -First 1).ToString().Trim()
}

function Wait-Ready {
    param([int]$TimeoutSeconds = 120)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if ((Get-ContainerState) -eq "running") {
            $reachable = Test-NetConnection -ComputerName "127.0.0.1" -Port $HostPort `
                -InformationLevel Quiet -WarningAction SilentlyContinue
            if ($reachable) {
                Write-Host "openGauss 已就绪：127.0.0.1:$HostPort"
                return
            }
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)

    throw "openGauss 容器已启动但端口 $HostPort 未就绪，请执行 -Action logs 查看日志。"
}

function Ensure-Running {
    $state = Get-ContainerState
    if ($state -eq $null) {
        throw "容器不存在：$ContainerName。先执行本脚本（默认 Action=up）创建。"
    }
    if ($state -ne "running") {
        Invoke-Podman @("start", $ContainerName)
        Wait-Ready
    }
}

switch ($Action) {
    "status" {
        if (-not (Test-Container)) {
            Write-Host "容器不存在：$ContainerName"
            break
        }
        Invoke-Podman @("ps", "--all", "--filter", "name=$ContainerName")
        break
    }
    "logs" {
        Ensure-Running
        Invoke-Podman @("logs", "--tail", $LogTail.ToString(), $ContainerName)
        break
    }
    "shell" {
        Ensure-Running
        & podman exec -it $ContainerName bash
        if ($LASTEXITCODE -ne 0) {
            throw "进入容器 shell 失败（exit $LASTEXITCODE）。"
        }
        break
    }
    "gsql" {
        Ensure-Running
        $gsql = 'export LD_LIBRARY_PATH=/usr/local/opengauss/lib:$LD_LIBRARY_PATH; /usr/local/opengauss/bin/gsql -h 127.0.0.1 -p 5432 -U gaussdb -d postgres'
        & podman exec -it $ContainerName sh -lc $gsql
        if ($LASTEXITCODE -ne 0) {
            throw "进入 gsql 失败（exit $LASTEXITCODE）。"
        }
        break
    }
    "start" {
        Ensure-Running
        Write-Host "容器已运行：$ContainerName"
        break
    }
    "stop" {
        if (Test-Container) {
            Invoke-Podman @("stop", $ContainerName)
            Write-Host "容器已停止：$ContainerName"
        } else {
            Write-Host "容器不存在：$ContainerName"
        }
        break
    }
    "restart" {
        if (Test-Container) {
            Invoke-Podman @("restart", $ContainerName)
            Wait-Ready
        } else {
            throw "容器不存在：$ContainerName。先执行 Action=up。"
        }
        break
    }
    "remove" {
        if (-not $Force) {
            throw "删除容器会丢失容器内数据；如确认，请追加 -Force。"
        }
        if (Test-Container) {
            Invoke-Podman @("rm", "--force", $ContainerName)
            Write-Host "容器已删除：$ContainerName"
        } else {
            Write-Host "容器不存在：$ContainerName"
        }
        break
    }
    "up" {
        if (Test-Container) {
            $state = Get-ContainerState
            if ($state -ne "running") {
                Invoke-Podman @("start", $ContainerName)
            }
        } else {
            Write-Host "创建 openGauss 容器：$ContainerName"
            Invoke-Podman @(
                "run", "--detach", "--name", $ContainerName,
                "--privileged=true",
                "--env", "GS_PASSWORD=$GaussPassword",
                "--publish", "$HostPort`:5432",
                $Image
            )
        }
        Wait-Ready
        Write-Host "JDBC URL：jdbc:gaussdb://127.0.0.1:$HostPort/postgres"
        Write-Host "JDBC 用户：gaussdb"
        Write-Host "JDBC 密码：$GaussPassword"
        Write-Host "驱动：请在 MagicCat 的‘工具 → 环境’中指定本地 gaussdbjdbc.jar"
        break
    }
}

