"""数据库方言注册表与连接 URL 构造（M25：为跨库扩展预留的接缝）。

当前实际支持：MySQL / MariaDB（经 mysql-connector-j，元数据走 information_schema）。
其它库：已在标准层就绪（JdbcStandardMetadata），此处登记驱动类/URL 模板，
接入时只需：pom 加驱动 + 此处 state 置 supported + java 选择实现（产品名已自动分流）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    key: str
    display: str
    driver_class: str
    url_template: str        # 值用 {host}/{port}/{database} 占位
    quote_open: str = '"'     # PostgreSQL 默认双引号；MySQL 用反引号
    quote_close: str = '"'
    state: str = "planned"    # supported | planned
    standard_metadata: bool = True  # 其它库走标准 DatabaseMetaData


PROVIDERS: dict[str, Provider] = {
    "mysql": Provider(
        key="mysql", display="MySQL", driver_class="com.mysql.cj.jdbc.Driver",
        url_template="jdbc:mysql://{host}:{port}/{database}",
        quote_open="`", quote_close="`", state="supported", standard_metadata=False),
    "mariadb": Provider(
        key="mariadb", display="MariaDB", driver_class="org.mariadb.jdbc.Driver",
        url_template="jdbc:mariadb://{host}:{port}/{database}",
        quote_open="`", quote_close="`", state="supported", standard_metadata=False),
    "postgresql": Provider(
        key="postgresql", display="PostgreSQL",
        driver_class="org.postgresql.Driver",
        url_template="jdbc:postgresql://{host}:{port}/{database}",
        state="planned", standard_metadata=True),
    "oracle": Provider(
        key="oracle", display="Oracle", driver_class="oracle.jdbc.OracleDriver",
        url_template="jdbc:oracle:thin:@//{host}:{port}/{database}",
        state="planned", standard_metadata=True),
    "sqlserver": Provider(
        key="sqlserver", display="SQL Server",
        driver_class="com.microsoft.sqlserver.jdbc.SQLServerDriver",
        url_template="jdbc:sqlserver://{host}:{port};databaseName={database}",
        state="planned", standard_metadata=True),
}

DEFAULT_KEY = "mysql"


def provider(key: str) -> Provider:
    return PROVIDERS.get(key, PROVIDERS[DEFAULT_KEY])


def supported_keys() -> list[str]:
    return [k for k, p in PROVIDERS.items() if p.state == "supported"]


def planned_keys() -> list[str]:
    return [k for k, p in PROVIDERS.items() if p.state == "planned"]


def build_jdbc_url(key: str, host: str, port: int, database: str = "") -> str:
    p = provider(key)
    return p.url_template.format(host=host, port=port, database=database)


def quote_ident(key: str, name: str) -> str:
    p = provider(key)
    return p.quote_open + name.replace(p.quote_close, p.quote_close * 2) + p.quote_close
