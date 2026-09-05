"""M106 回归：GaussDB 表对象页不能复用 MySQL 反引号查询。"""

from __future__ import annotations


def test_gaussdb_schema_tables_uses_catalog_schema_path(monkeypatch):
    from magiccat.models.profile import ConnectionProfile
    from magiccat.services.metadata_service import MetadataService

    profile = ConnectionProfile(
        name="GaussDB", provider_key="GaussDB", database="aps"
    )
    service = object.__new__(MetadataService)
    calls: list[tuple[str, str, str]] = []

    def standard_path(_profile, database: str, schema: str):
        calls.append((database, schema, _profile.provider_key))
        return [{"name": "t_demo", "type": "BASE TABLE"}]

    monkeypatch.setattr(service, "schema_tables_in_database", standard_path)
    monkeypatch.setattr(
        service,
        "_meta",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("GaussDB 不应调用 MySQL schemaTables")
        ),
    )

    assert service.schema_tables(profile, "public", "aps") == [
        {"name": "t_demo", "type": "BASE TABLE"}
    ]
    assert calls == [("aps", "public", "GaussDB")]

