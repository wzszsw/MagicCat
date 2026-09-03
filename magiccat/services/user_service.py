"""用户管理（M47）：MySQL 用户列表 + 新建/编辑/删除 + 权限查看。"""

from __future__ import annotations

from magiccat.models.profile import ConnectionProfile
from magiccat.services.query_service import QueryService

_LIST_SQL = (
    "SELECT User AS user, Host AS host, plugin, ssl_type, "
    "max_questions AS max_questions, max_updates AS max_updates, "
    "max_connections AS max_connections, "
    "max_user_connections AS max_user_connections, super_priv AS super_priv "
    "FROM mysql.user ORDER BY User, Host")


def _quote(user: str, host: str) -> str:
    return f"'{user.replace(chr(39), chr(39) * 2)}'@'{host.replace(chr(39), chr(39) * 2)}'"


def list_users(query: QueryService, profile: ConnectionProfile) -> list[dict]:
    """返回 [{user,host,plugin,ssl_type,max_questions,...}]。"""
    res = query.execute(profile, _LIST_SQL)[0]
    cols = res.get("columns", [])
    return [dict(zip(cols, row)) for row in res.get("rows", [])]


def create_user(query: QueryService, profile: ConnectionProfile, user: str, host: str,
                password: str) -> None:
    if not user or not host:
        raise ValueError("用户名与主机不能为空")
    ident = _quote(user, host)
    if password:
        sql = f"CREATE USER {ident} IDENTIFIED BY '{password.replace(chr(39), chr(39) * 2)}'"
    else:
        sql = f"CREATE USER {ident}"
    results = query.execute(profile, sql)
    _raise_if_error(results, "创建用户")


def alter_password(query: QueryService, profile: ConnectionProfile, user: str, host: str,
                   password: str) -> None:
    if not password:
        raise ValueError("密码不能为空")
    sql = (f"ALTER USER {_quote(user, host)} "
           f"IDENTIFIED BY '{password.replace(chr(39), chr(39) * 2)}'")
    _raise_if_error(query.execute(profile, sql), "修改密码")


def drop_user(query: QueryService, profile: ConnectionProfile, user: str, host: str) -> None:
    _raise_if_error(query.execute(profile, f"DROP USER {_quote(user, host)}"), "删除用户")


def show_grants(query: QueryService, profile: ConnectionProfile, user: str, host: str) -> str:
    res = query.execute(profile, f"SHOW GRANTS FOR {_quote(user, host)}")
    _raise_if_error(res, "读取权限")
    lines = []
    for row in res[0].get("rows", []):
        lines.extend(str(v) for v in row if v is not None)
    return "\n".join(lines) if lines else "（无授权）"


def _raise_if_error(results: list[dict], action: str) -> None:
    errors = [r for r in results if r.get("kind") == "error"]
    if errors:
        raise RuntimeError(f"{action}失败: {errors[0]['message']}")
