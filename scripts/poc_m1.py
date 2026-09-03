"""M1 技术验证 POC：PySide6(界面未接入) -> JPype -> HikariCP -> mysql-connector-j -> 本机 MySQL。

运行前提：
  1) scripts/build_java.ps1 已构建 java-bridge（生成 target/magiccat-bridge-*.jar 与 target/lib）；
  2) 本机 MySQL 监听 127.0.0.1:3306（root 空密码，数据不重要，仅用于开发测试）。
运行方式（在仓库根目录）：
  uv run python scripts/poc_m1.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magiccat.bridge.jvm import BridgeRuntime  # noqa: E402

# ---- 本机开发库参数（数据不重要） ----
HOST = "127.0.0.1"
PORT = 3306
USER = "root"
PASSWORD = ""


def cell(v) -> str:
    return "<NULL>" if v is None else str(v)


def main() -> int:
    bridge = BridgeRuntime()
    bridge.start()
    print(f"[1/3] JVM 已启动，classpath 就绪")
    try:
        Facade = bridge.jclass("com.magiccat.bridge.Facade")

        # 1) 连通性自检
        version = Facade.ping(HOST, PORT, USER, PASSWORD)
        print(f"[2/3] ping -> MySQL VERSION = {version}")

        # 2) 元数据查询（证明 Hikari 池 + ResultSetMetaData + 多行取数）
        rows = Facade.query(HOST, PORT, "mysql", USER, PASSWORD, "SHOW DATABASES", 20)
        print(f"[3/3] SHOW DATABASES -> {len(rows)} 行")
        for i, row in enumerate(rows):
            print(f"      [{i}] " + " | ".join(cell(c) for c in row))

        # 3) 类型与 NULL 抽查（Decimal / 字符串 / NULL 单元格）
        typed = Facade.query(
            HOST, PORT, "mysql", USER, PASSWORD,
            "SELECT 1 AS i, 3.14159 AS d, '你好 MagicCat' AS s, NULL AS n, TRUE AS b", 5,
        )
        print("      类型抽查: " + " | ".join(cell(c) for c in typed[0]))
    finally:
        bridge.shutdown()
    print("POC 通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
