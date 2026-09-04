package com.magiccat.bridge;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.net.MalformedURLException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
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
    /** 每个配置的连接参数（用于对目标 database 临时建连，供跨库元数据）。 */
    private static final ConcurrentHashMap<String, ConnectParams> PARAMS = new ConcurrentHashMap<>();
    /** 外置版权驱动的 classloader：只保留引用，不复制 JAR 内容。 */
    private static final ConcurrentHashMap<String, URLClassLoader> EXTERNAL_DRIVER_LOADERS =
            new ConcurrentHashMap<>();

    /** 连接参数（host/port/database/user/pass/flavor/外置驱动）。 */
    public record ConnectParams(String configId, String flavor, String host, int port,
                                String database, String user, String password,
                                String driverJar) {}

    private ConnectionRegistry() {}

    /** 打开（或替换）一个连接池。重复 open 会先关闭旧池。 */
    public static String open(String configId, String host, int port, String database,
                              String user, String password) {
        return open(configId, "mysql", host, port, database, user, password, "");
    }

    /** 打开（或替换）一个连接池；flavor 为方言 key（mysql/mariadb/postgresql…）。 */
    public static String open(String configId, String flavor, String host, int port,
                              String database, String user, String password) {
        return open(configId, flavor, host, port, database, user, password, "");
    }

    /** 打开或替换连接池；GaussDB 的 driverJar 是用户通过“环境”指定的本地 JAR。 */
    public static String open(String configId, String flavor, String host, int port,
                              String database, String user, String password,
                              String driverJar) {
        close(configId);
        PARAMS.put(configId, new ConnectParams(configId, flavor, host, port, database,
                user, password, driverJar));
        POOLS.put(configId, newDataSource(flavor, host, port, database, user, password,
                driverJar, 8, "mc-" + configId));
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
        return executeScript(configId, "", schema, statements);
    }

    /** 批量执行；database 仅 PG 跨库时有意义（连到目标库）。 */
    public static String executeScript(String configId, String database,
                                       String schema, String[] statements) {
        List<String> results = new ArrayList<>();
        try (Connection conn = connectionTo(configId, database)) {
            if (schema != null && !schema.isBlank()) {
                boolean pg = isPostgres(configId);
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

    /** 该配置是否为 PostgreSQL 兼容产品（按连接时的 flavor 判定）。 */
    public static boolean isPostgres(String configId) {
        ConnectParams p = PARAMS.get(configId);
        return p != null && ("postgresql".equalsIgnoreCase(p.flavor())
                || "gaussdb".equalsIgnoreCase(p.flavor()));
    }

    /** 若是 PG 且指定了 database，则对【该库】建临时连接（跨库访问）；否则用连接池连接。 */
    static Connection connectionTo(String configId, String database) throws SQLException {
        ConnectParams p = PARAMS.get(configId);
        if (p == null) {
            throw new IllegalStateException("连接参数缺失: " + configId);
        }
        if (database != null && !database.isBlank() && isPostgres(configId)) {
            return newDataSource(p.flavor(), p.host(), p.port(),
                    database, p.user(), p.password(), p.driverJar(), 2,
                    "mc-tmp-" + p.host() + ":" + p.port() + "/" + database).getConnection();
        }
        return requirePool(configId).getConnection();
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

    /** 取该配置的连接参数（跨库临时连接用）；未记录则返回 null。 */
    public static ConnectParams params(String configId) {
        return PARAMS.get(configId);
    }

    /** 在【目标 database】上临时建单连接执行查询并返回 JSON 表。
     * 用于跨库枚举：如 PG 需连到 database X 才能列其 schema/对象。
     * 连接用完即关，不入池。 */
    public static String executeOnDatabase(String configId, String database,
                                          String sql, String[] params, int maxRows) {
        ConnectParams p = PARAMS.get(configId);
        if (p == null) {
            throw new IllegalStateException("连接参数缺失: " + configId);
        }
        try (HikariDataSource ds = newDataSource(p.flavor(), p.host(), p.port(),
                                                 database, p.user(), p.password(), p.driverJar(), 2,
                                                 "mc-tmp-" + p.host() + ":" + p.port() + "/" + database);
             Connection conn = ds.getConnection();
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
                String[] columns = new String[n];
                for (int i = 1; i <= n; i++) {
                    columns[i - 1] = md.getColumnLabel(i);
                }
                List<String[]> rows = new ArrayList<>();
                while (rs.next()) {
                    String[] row = new String[n];
                    for (int i = 1; i <= n; i++) {
                        row[i - 1] = Facade.cellToString(rs.getObject(i));
                    }
                    rows.add(row);
                }
                return Json.table(columns, rows);
            }
        } catch (SQLException e) {
            throw new IllegalStateException("跨库查询失败: " + e.getMessage(), e);
        }
    }

    static HikariDataSource newDataSource(String flavor, String host, int port,
                                          String database, String user, String password,
                                          String driverJar, int maxPoolSize,
                                          String poolName) {
        ClassLoader previous = Thread.currentThread().getContextClassLoader();
        if ("gaussdb".equalsIgnoreCase(flavor)) {
            Thread.currentThread().setContextClassLoader(externalDriverLoader(driverJar));
        }
        try {
            HikariConfig cfg = new HikariConfig();
            cfg.setJdbcUrl(Facade.buildUrlByFlavor(flavor, host, port, database));
            cfg.setUsername(user);
            cfg.setPassword(password == null ? "" : password);
            cfg.setMaximumPoolSize(maxPoolSize);
            cfg.setConnectionTimeout(10_000);
            cfg.setPoolName(poolName);
            if (!"gaussdb".equalsIgnoreCase(flavor)) {
                return new HikariDataSource(cfg);
            }
            cfg.setDriverClassName("com.huawei.gaussdb.jdbc.Driver");
            return new HikariDataSource(cfg);
        } finally {
            Thread.currentThread().setContextClassLoader(previous);
        }
    }

    private static URLClassLoader externalDriverLoader(String driverJar) {
        if (driverJar == null || driverJar.isBlank()) {
            throw new IllegalArgumentException("GaussDB 需要在“工具 → 环境”指定本地 JDBC 驱动 JAR");
        }
        Path jarPath = Path.of(driverJar).toAbsolutePath().normalize();
        if (!Files.isRegularFile(jarPath)) {
            throw new IllegalArgumentException("GaussDB JDBC 驱动不存在: " + jarPath);
        }
        String key = jarPath.toString();
        return EXTERNAL_DRIVER_LOADERS.computeIfAbsent(key, ConnectionRegistry::newDriverLoader);
    }

    private static URLClassLoader newDriverLoader(String jarPath) {
        try {
            URL url = Path.of(jarPath).toUri().toURL();
            return new URLClassLoader(new URL[] {url}, ConnectionRegistry.class.getClassLoader());
        } catch (MalformedURLException e) {
            throw new IllegalArgumentException("GaussDB JDBC 驱动路径无效: " + jarPath, e);
        }
    }
}
