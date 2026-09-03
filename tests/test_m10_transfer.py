"""M10 测试：库间/表间数据传输（结构+数据复制）。"""

from __future__ import annotations

import time

from magiccat.models.profile import DEFAULT_GROUP, ConnectionProfile
from magiccat.services import transfer


def test_copy_table_structure_and_data(mysql_env, connection_service):
    from magiccat.services.data_service import DataService
    from magiccat.services.metadata_service import MetadataService
    from magiccat.services.query_service import QueryService

    profile = ConnectionProfile(name="M10", group=DEFAULT_GROUP, database="test",
                                host=mysql_env["host"], port=mysql_env["port"],
                                username=mysql_env["user"], password=mysql_env["password"])
    connection_service.add(profile)
    q = QueryService(connection_service)
    data = DataService(connection_service)
    meta = MetadataService(connection_service)
    suffix = int(time.time() * 1000)
    src = f"mc_m10_src_{suffix}"
    dst = f"mc_m10_dst_{suffix}"
    dst2 = f"mc_m10_dst2_{suffix}"
    try:
        q.execute(profile, (
            f"CREATE TABLE `{src}` (id INT PRIMARY KEY, name VARCHAR(30) NOT NULL, "
            "note VARCHAR(50) NULL) ENGINE=InnoDB"))
        q.execute(profile, (
            f"INSERT INTO `{src}` VALUES (1, 'a', NULL), (2, 'b', '备注'), (3, '丙·文', NULL)"))

        # 结构 + 数据
        res = transfer.copy_table_data(profile, "test", src, "test", dst,
                                       q, data, meta, with_structure=True)
        assert res["rows"] == 3
        rows = q.execute(profile, f"SELECT * FROM `{dst}` ORDER BY id")
        values = rows[0]["rows"]
        assert [r[0] for r in values] == ["1", "2", "3"]
        assert values[0][2] is None and values[1][2] == "备注" and values[2][1] == "丙·文"

        # 数据追加到已存在空表（不重建结构）
        q.execute(profile, f"CREATE TABLE `{dst2}` LIKE `{src}`")
        res2 = transfer.copy_table_data(profile, "test", src, "test", dst2,
                                        q, data, meta, with_structure=False)
        assert res2["rows"] == 3
        count = q.execute(profile, f"SELECT COUNT(*) FROM `{dst2}`")
        assert count[0]["rows"] == [["3"]]
    finally:
        q.execute(profile, f"DROP TABLE IF EXISTS `{dst}`")
        q.execute(profile, f"DROP TABLE IF EXISTS `{dst2}`")
        q.execute(profile, f"DROP TABLE IF EXISTS `{src}`")
        connection_service.close(profile.id)
