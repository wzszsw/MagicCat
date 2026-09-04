"""M108 回归：openGauss Podman 助手脚本保留可重复启动和显式删除语义。"""

from __future__ import annotations

from pathlib import Path


def test_opengauss_script_has_safe_lifecycle_defaults() -> None:
    script = (Path(__file__).parents[1] / "scripts" / "opengauss.ps1").read_text(
        encoding="utf-8"
    )

    assert 'ContainerName = "magiccat-opengauss"' in script
    assert 'Image = "docker.io/library/opengauss:6.0.3"' in script
    assert 'HostPort = 15432' in script
    assert 'ValidateSet("up", "start", "stop", "restart", "status", "logs", "shell", "gsql", "remove")' in script
    assert '"--env", "GS_PASSWORD=$GaussPassword"' in script
    assert '"--publish", "$HostPort`:5432"' in script
    assert 'if (-not $Force)' in script
    assert "jdbc:gaussdb://127.0.0.1:$HostPort/postgres" in script
