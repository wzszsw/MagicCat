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
                password: str = "", plugin: str = "", expire: str = "DEFAULT") -> None:
    if not user or not host:
        raise ValueError("用户名与主机不能为空")
    ident = _quote(user, host)
    sql = f"CREATE USER {ident}" + _auth_clause(password, plugin) + _expire_clause(expire)
    _raise_if_error(query.execute(profile, sql), "创建用户")


def alter_user(query: QueryService, profile: ConnectionProfile, user: str, host: str,
               password: str = "", plugin: str = "", expire: str = "DEFAULT",
               change_credentials: bool = True) -> None:
    """修改用户：可改 插件/密码（change_credentials 控制是否生成 IDENTIFIED 子句）
    与密码过期策略。password 为空但不改凭据时跳过 IDENTIFIED。"""
    ident = _quote(user, host)
    parts = []
    if password:
        parts.append(_auth_clause(password, plugin))
    if expire:
        parts.append(_expire_clause(expire))
    if not parts:
        raise ValueError("没有要修改的项目")
    sql = f"ALTER USER {ident} " + " ".join(parts)
    _raise_if_error(query.execute(profile, sql), "修改用户")


def alter_password(query: QueryService, profile: ConnectionProfile, user: str, host: str,
                   password: str) -> None:
    if not password:
        raise ValueError("密码不能为空")
    alter_user(query, profile, user, host, password=password)


def _auth_clause(password: str, plugin: str) -> str:
    clause = ""
    if plugin:
        clause += f" IDENTIFIED WITH '{plugin.replace(chr(39), chr(39) * 2)}'"
    if password:
        clause += f" BY '{password.replace(chr(39), chr(39) * 2)}'"
    return clause


def _expire_clause(expire: str) -> str:
    upper = (expire or "DEFAULT").strip().upper()
    if upper == "DEFAULT":
        return " PASSWORD EXPIRE DEFAULT"
    if upper == "NEVER":
        return " PASSWORD EXPIRE NEVER"
    if upper.startswith("INTERVAL"):
        days = upper.replace("INTERVAL", "").replace("DAY", "").strip() or "90"
        return f" PASSWORD EXPIRE INTERVAL {int(days)} DAY"
    return ""


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
