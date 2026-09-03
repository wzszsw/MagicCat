"""M2 冒烟脚本：加密配置存取 + 真实连接 + 元数据（对象树数据源）全链路验证。

运行前提：java-bridge 已构建；本机 MySQL 127.0.0.1:3306 root 空密码。
数据文件写入仓库 .devdata/（不入库），用完可删。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MAGICCAT_HOME", str(ROOT / ".devdata"))

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services.connection_service import ConnectionService
from magiccat.services.metadata_service import MetadataService
from magiccat.services.profile_store import ProfileStore

HOST, PORT, USER, PASSWORD = "127.0.0.1", 3306, "root", ""
SECRET = "s3cret中文!@#pass"  # 仅用于验证加密存取，非真实连接口令


def main() -> int:
    store = ProfileStore()
    conns = ConnectionService(store)
    meta = MetadataService(conns)

    # 1) 新增并落盘（口令先放一个“假秘密”，验证加密）
    profile = ConnectionProfile(name="本地开发 MySQL", group=DEFAULT_GROUP,
                                host=HOST, port=PORT, username=USER, password=SECRET)
    conns.add(profile)
    print(f"[1/6] 已保存连接 {profile.name} (id={profile.id[:8]}…)")

    # 2) 从磁盘重读，验证 DPAPI 加密口令回环
    reloaded = ConnectionService(ProfileStore()).get(profile.id)
    assert reloaded is not None and reloaded.password == SECRET, "口令回环失败"
    assert SECRET not in store.file.read_text(encoding="utf-8"), "口令不应明文落盘"
    print("[2/6] DPAPI 口令加密/解密回环 OK（文件无明文口令）")

    # 3) 换回真实（空）口令并打开连接
    profile.password = PASSWORD
    conns.update(profile)
    version = conns.open(profile)
    print(f"[3/6] open -> MySQL {version}")

    # 4) 数据库列表
    dbs = [d["name"] for d in meta.databases(profile)]
    print(f"[4/6] databases({len(dbs)}) = {dbs[:6]}{' …' if len(dbs) > 6 else ''}")
    assert "mysql" in dbs and "information_schema" in dbs

    # 5) 对象树数据源：表 + 例程 + 触发器
    tables = meta.tables(profile, "mysql")
    print(f"[5/6] mysql.tables = {len(tables)}（含视图）; routines={len(meta.routines(profile, 'mysql'))}"
          f"; triggers={len(meta.triggers(profile, 'mysql'))}")
    assert tables

    # 6) 列定义 + 索引（供 M4 表设计器复用）
    t = next(t for t in tables if t["type"] == "BASE TABLE")
    cols = meta.columns(profile, "mysql", t["name"])
    idxs = meta.indexes(profile, "mysql", t["name"])
    print(f"[6/6] {t['name']}: {len(cols)} 列 / {len(idxs)} 条索引；首列示例 = {cols[0]}")
    assert cols

    conns.close(profile.id)
    conns.close_all()
    print("M2 冒烟通过 ✔（连接已关闭）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
