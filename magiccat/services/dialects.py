"""数据库方言注册表与应用层能力构造。

当前实际支持：MySQL / MariaDB（mysql-connector-j，元数据走 information_schema）、
PostgreSQL（postgresql 驱动，元数据走标准 DatabaseMetaData）、GaussDB
（PG 兼容语义，用户手动指定受版权约束的 JDBC JAR）。
Oracle / SQL Server：已在标准层就绪，接入时只需 pom 加驱动 + 此处 state 置 supported。

``Dialect`` 描述应用层可以依赖的产品能力。它不改变 JDBC 的 catalog/schema
传参语义：MySQL/MariaDB 仍由底层视为 catalog + ``schema=null``，这里只负责
界面领域、分页 SQL 和产品能力判断。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dialect:
    key: str
    display: str
    driver_class: str
    url_template: str        # 值用 {host}/{port}/{database} 占位
    quote_open: str = '"'     # PostgreSQL 默认双引号；MySQL 用反引号
    quote_close: str = '"'
    state: str = "planned"    # supported | planned
    standard_metadata: bool = True  # 其它库走标准 DatabaseMetaData
    requires_external_driver: bool = False
    supports_schema: bool = True
    supports_sequences: bool = False
    pagination_style: str = "limit_offset"
    database_is_schema: bool = False
    requires_initial_database: bool = False
    postgres_compatible: bool = False

    def pagination_clause(self, offset: int, limit: int) -> str:
        """返回不含前导空格的分页片段。"""
        safe_offset = max(int(offset), 0)
        safe_limit = max(int(limit), 1)
        if self.pagination_style == "mysql_limit":
            return f"LIMIT {safe_offset}, {safe_limit}"
        if self.pagination_style == "offset_fetch":
            return (f"OFFSET {safe_offset} ROWS "
                    f"FETCH NEXT {safe_limit} ROWS ONLY")
        return f"LIMIT {safe_limit} OFFSET {safe_offset}"


# 旧调用方只使用注册表中的对象，不再额外维护一套 Provider 类型名。
Provider = Dialect


PROVIDERS: dict[str, Dialect] = {
    "MYSQL": Dialect(
        key="MYSQL", display="MySQL", driver_class="com.mysql.cj.jdbc.Driver",
        url_template="jdbc:mysql://{host}:{port}/{database}",
        quote_open="`", quote_close="`", state="supported", standard_metadata=False,
        supports_schema=False, pagination_style="mysql_limit", database_is_schema=True),
    "MARIADB": Dialect(
        key="MARIADB", display="MariaDB", driver_class="org.mariadb.jdbc.Driver",
        url_template="jdbc:mariadb://{host}:{port}/{database}",
        quote_open="`", quote_close="`", state="supported", standard_metadata=False,
        supports_schema=False, pagination_style="mysql_limit", database_is_schema=True),
    "PGSQL": Dialect(
        key="PGSQL", display="PostgreSQL",
        driver_class="org.postgresql.Driver",
        url_template="jdbc:postgresql://{host}:{port}/{database}",
        state="supported", standard_metadata=True, supports_schema=True,
        supports_sequences=True, requires_initial_database=True,
        postgres_compatible=True),
    "GAUSSDB": Dialect(
        key="GAUSSDB", display="GaussDB",
        driver_class="com.huawei.gaussdb.jdbc.Driver",
        url_template="jdbc:gaussdb://{host}:{port}/{database}",
        state="supported", standard_metadata=True, requires_external_driver=True,
        supports_schema=True, supports_sequences=True, requires_initial_database=True,
        postgres_compatible=True),
    "ORACLE": Dialect(
        key="ORACLE", display="Oracle", driver_class="oracle.jdbc.OracleDriver",
        url_template="jdbc:oracle:thin:@//{host}:{port}/{database}",
        state="planned", standard_metadata=True, supports_schema=True,
        supports_sequences=True),
    "MSSQL": Dialect(
        key="MSSQL", display="SQL Server",
        driver_class="com.microsoft.sqlserver.jdbc.SQLServerDriver",
        url_template="jdbc:sqlserver://{host}:{port};databaseName={database}",
        state="planned", standard_metadata=True, supports_schema=True,
        supports_sequences=True, pagination_style="offset_fetch"),
}

DEFAULT_KEY = "MYSQL"
DEFAULT_PAGE_SIZE = 1000


def dialect(key: str) -> Dialect:
    """返回应用层方言；未知产品沿用 MySQL 默认行为。"""
    return PROVIDERS.get(key, PROVIDERS[DEFAULT_KEY])


def provider(key: str) -> Dialect:
    """兼容旧入口；新代码优先使用 ``dialect``。"""
    return dialect(key)


def supported_keys() -> list[str]:
    return [k for k, p in PROVIDERS.items() if p.state == "supported"]


def planned_keys() -> list[str]:
    return [k for k, p in PROVIDERS.items() if p.state == "planned"]


def build_jdbc_url(key: str, host: str, port: int, database: str = "") -> str:
    p = dialect(key)
    return p.url_template.format(host=host, port=port, database=database)


def quote_ident(key: str, name: str) -> str:
    p = dialect(key)
    return p.quote_open + name.replace(p.quote_close, p.quote_close * 2) + p.quote_close


def supports_schema(key: str) -> bool:
    return dialect(key).supports_schema


def supports_sequences(key: str) -> bool:
    return dialect(key).supports_sequences


def requires_initial_database(key: str) -> bool:
    return dialect(key).requires_initial_database


def database_is_schema(key: str) -> bool:
    return dialect(key).database_is_schema


def pagination_clause(key: str, offset: int, limit: int) -> str:
    """按应用方言生成分页语法，不触碰 JDBC catalog/schema 语义。"""
    return dialect(key).pagination_clause(offset, limit)
