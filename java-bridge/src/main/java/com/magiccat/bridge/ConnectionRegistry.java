package com.magiccat.bridge;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 连接池注册表：按配置 ID（configId，由 Python 侧生成并保持稳定）管理 HikariCP 连接池。
 *
 * <p>所有 JDBC 调用收敛于此（设计方案 §4.1），静态实现便于 JPype 直调；
 * 后续若改独立桥接进程，仅需把这组静态方法迁到服务端。
 */
public final class ConnectionRegistry {

    private static final ConcurrentHashMap<String, HikariDataSource> POOLS = new ConcurrentHashMap<>();
    /** 可取消执行的活跃语句表（令牌 → Statement）。 */
    private static final ConcurrentHashMap<String, Statement> ACTIVE = new ConcurrentHashMap<>();

    private ConnectionRegistry() {}

    /** 打开（或替换）一个连接池。重复 open 会先关闭旧池。 */
    public static String open(String configId, String host, int port, String database,
                              String user, String password) {
        return open(configId, "mysql", host, port, database, user, password);
    }

    /** 打开（或替换）一个连接池；flavor 为方言 key（mysql/mariadb/postgresql…）。 */
    public static String open(String configId, String flavor, String host, int port,
                              String database, String user, String password) {
        close(configId);
        HikariConfig cfg = new HikariConfig();
        cfg.setJdbcUrl(Facade.buildUrlByFlavor(flavor, host, port, database));
        cfg.setUsername(user);
        cfg.setPassword(password == null ? "" : password);
        cfg.setMaximumPoolSize(8);
        cfg.setConnectionTimeout(10_000);
        cfg.setPoolName("mc-" + configId);
        POOLS.put(configId, new HikariDataSource(cfg));
        return configId;
    }

    /** 连通性自检，返回数据库版本。 */
    public static String ping(String configId) {
        try (Connection conn = requirePool(configId).getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT VERSION()")) {
            rs.next();
            return rs.getString(1);
        } catch (SQLException e) {
            throw new IllegalStateException("连接不可用: " + e.getMessage(), e);
        }
    }

    /**
     * 通用查询：返回 {"columns":[...],"rows":[[...]]} JSON；NULL 单元格为 null。
     * params 可为 null；maxRows &lt;= 0 表示不限制。
     */
    public static String executeJson(String configId, String sql, String[] params, int maxRows) {
        List<String[]> rows = new ArrayList<>();
        String[] columns;
        try (Connection conn = requirePool(configId).getConnection();
             PreparedStatement ps = conn.prepareStatement(sql)) {
            if (maxRows > 0) {
                ps.setMaxRows(maxRows);
            }
            if (params != null) {
                for (int i = 0; i < params.length; i++) {
                    ps.setString(i + 1, params[i]);
                }
            }
            try (ResultSet rs = ps.executeQuery()) {
                ResultSetMetaData md = rs.getMetaData();
                int n = md.getColumnCount();
                columns = new String[n];
                for (int i = 1; i <= n; i++) {
                    columns[i - 1] = md.getColumnLabel(i);
                }
                while (rs.next()) {
                    String[] row = new String[n];
                    for (int i = 1; i <= n; i++) {
                        row[i - 1] = Facade.cellToString(rs.getObject(i));
                    }
                    rows.add(row);
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("查询失败: " + e.getMessage(), e);
        }
        return Json.table(columns, rows);
    }

    /**
     * 执行任意单条语句并自动分拣结果：
     * 查询类（SELECT/SHOW/DESCRIBE…）→ {"kind":"query","columns":[...],"rows":[...]}；
     * 更新类（INSERT/UPDATE/DDL…）→ {"kind":"update","affected":N}。
     */
    public static String execute(String configId, String sql, int maxRows) {
        return run(configId, sql, maxRows, null);
    }

    /** 可取消执行：注册令牌 → 其他线程可调 cancelToken 中断当前语句。 */
    public static String executeCancelable(String configId, String sql, int maxRows,
                                           String token) {
        return run(configId, sql, maxRows, token);
    }

    /** 中断某令牌正在执行的语句（无令牌或已结束则空操作）。 */
    public static void cancelToken(String token) {
        if (token == null) {
            return;
        }
        Statement st = ACTIVE.get(token);
        if (st != null) {
            try {
                st.cancel();
            } catch (SQLException ignored) {
                // 语句可能已自然结束
            }
        }
    }

    /** 在单条连接（可先指定默认库）上顺序执行语句，供脚本恢复使用。
     * 返回 JSON 数组：[{"kind":"update","affected":N} | {"kind":"error","message":…}]。
     * 默认库切换：PostgreSQL 用 setSchema，MySQL/MariaDB 用 setCatalog。 */
    public static String executeScript(String configId, String schema, String[] statements) {
        List<String> results = new ArrayList<>();
        try (Connection conn = requirePool(configId).getConnection()) {
            if (schema != null && !schema.isBlank()) {
                boolean pg = isPostgres(conn);
                if (pg) {
                    conn.setSchema(schema);
                } else {
                    conn.setCatalog(schema);
                }
            }
            for (String sql : statements) {
                if (sql == null || sql.isBlank()) {
                    continue;
                }
                try (Statement st = conn.createStatement()) {
                    boolean hasRs = st.execute(sql);
                    int affected = hasRs ? 0 : Math.max(st.getUpdateCount(), 0);
                    results.add(Json.updateResult(affected));
                } catch (SQLException e) {
                    results.add("{\"kind\":\"error\",\"message\":"
                            + Json.q(e.getMessage() == null ? "未知错误" : e.getMessage()) + "}");
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("执行脚本失败: " + e.getMessage(), e);
        }
        return "[" + String.join(",", results) + "]";
    }

    private static boolean isPostgres(Connection conn) {
        try {
            String product = conn.getMetaData().getDatabaseProductName();
            return product != null && product.toLowerCase().contains("postgresql");
        } catch (SQLException e) {
            return false;
        }
    }

    private static String run(String configId, String sql, int maxRows, String token) {
        List<String[]> rows = new ArrayList<>();
        String[] columns;
        try (Connection conn = requirePool(configId).getConnection();
             Statement st = conn.createStatement()) {
            if (maxRows > 0) {
                st.setMaxRows(maxRows);
            }
            if (token != null) {
                ACTIVE.put(token, st);
            }
            try {
                boolean hasResult = st.execute(sql);
                if (!hasResult) {
                    return Json.updateResult(st.getUpdateCount());
                }
                try (ResultSet rs = st.getResultSet()) {
                    ResultSetMetaData md = rs.getMetaData();
                    int n = md.getColumnCount();
                    columns = new String[n];
                    for (int i = 1; i <= n; i++) {
                        columns[i - 1] = md.getColumnLabel(i);
                    }
                    while (rs.next()) {
                        String[] row = new String[n];
                        for (int i = 1; i <= n; i++) {
                            row[i - 1] = Facade.cellToString(rs.getObject(i));
                        }
                        rows.add(row);
                    }
                }
                return Json.queryResult(columns, rows);
            } finally {
                if (token != null) {
                    ACTIVE.remove(token);
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("执行失败: " + e.getMessage(), e);
        }
    }

    /** 关闭某个连接池。 */
    public static void close(String configId) {
        HikariDataSource ds = POOLS.remove(configId);
        if (ds != null) {
            ds.close();
        }
    }

    /** 关闭全部连接池（应用退出时调用）。 */
    public static void closeAll() {
        for (String id : POOLS.keySet()) {
            close(id);
        }
    }

    /** 当前打开的配置 ID 集合（调试/状态显示用）。 */
    public static String[] openIds() {
        return POOLS.keySet().toArray(new String[0]);
    }

    static HikariDataSource requirePool(String configId) {
        HikariDataSource ds = POOLS.get(configId);
        if (ds == null) {
            throw new IllegalStateException("连接尚未打开或已被关闭: " + configId);
        }
        return ds;
    }
}
