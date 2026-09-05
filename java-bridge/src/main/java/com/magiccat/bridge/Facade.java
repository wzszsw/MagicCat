package com.magiccat.bridge;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;

/**
 * M1 兼容门面：验证 JPype -> JDBC 驱动 -> MySQL 全链路。
 *
 * <p>后续里程碑将演进为按连接配置 ID 管理的多会话门面（ConnectionRegistry /
 * MetadataEngine / QueryExecutor / Dialect SPI 等，见 docs/MagicCat设计方案.md §4）。
 * 当前方法均为静态、无状态、每次建立一次性 JDBC 连接，仅用于兼容技术验证。
 */
public final class Facade {

    private Facade() {}

    public static String buildUrl(String host, int port, String database) {
        String db = (database == null || database.isBlank()) ? "" : database;
        return "jdbc:mysql://" + host + ":" + port + "/" + db
                + "?useUnicode=true&characterEncoding=utf8"
                + "&sslMode=DISABLED&allowPublicKeyRetrieval=true"
                + "&connectTimeout=5000&socketTimeout=30000&serverTimezone=UTC";
    }

    /** 按方言构造 JDBC URL（MySQL/MariaDB 含参数；PG 兼容产品走各自协议）。 */
    public static String buildUrlByFlavor(String flavor, String host, int port,
                                          String database) {
        String db = (database == null || database.isBlank()) ? "" : database;
        String f = flavor == null ? "" : flavor.toLowerCase();
        if ("postgresql".equals(f)) {
            // PostgreSQL 使用自身默认连接参数；不要注入项目约定的 MySQL 参数。
            return "jdbc:postgresql://" + host + ":" + port + "/" + db;
        }
        if ("gaussdb".equals(f)) {
            // GaussDB URL 不注入项目约定的 MySQL connect/socket 参数。
            return "jdbc:gaussdb://" + host + ":" + port + "/" + db;
        }
        // 默认按 MySQL/MariaDB 处理
        return "jdbc:mysql://" + host + ":" + port + "/" + db
                + "?useUnicode=true&characterEncoding=utf8"
                + "&sslMode=DISABLED&allowPublicKeyRetrieval=true"
                + "&connectTimeout=5000&socketTimeout=30000&serverTimezone=UTC";
    }

    /** 连通性自检：SELECT VERSION()，返回数据库版本字符串。 */
    public static String ping(String host, int port, String user, String password) {
        try (Connection conn = DriverManager.getConnection(buildUrl(host, port, null), user,
                                                            password == null ? "" : password);
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT VERSION()")) {
            rs.next();
            return rs.getString(1);
        } catch (SQLException e) {
            throw new IllegalStateException("数据库连接失败: " + e.getMessage(), e);
        }
    }

    /**
     * 执行只读查询并取回最多 maxRows 行。
     * NULL 单元格对应 null；单元格统一转字符串（BLOB 截断为 0x 十六进制预览）。
     */
    public static String[][] query(String host, int port, String database, String user,
                                   String password, String sql, int maxRows) {
        List<String[]> rows = new ArrayList<>();
        try (Connection conn = DriverManager.getConnection(buildUrl(host, port, database), user,
                                                            password == null ? "" : password);
             Statement st = conn.createStatement()) {
            if (maxRows > 0) {
                st.setMaxRows(maxRows);
            }
            try (ResultSet rs = st.executeQuery(sql)) {
                ResultSetMetaData md = rs.getMetaData();
                int cols = md.getColumnCount();
                while (rs.next()) {
                    String[] row = new String[cols];
                    for (int i = 1; i <= cols; i++) {
                        row[i - 1] = cellToString(rs.getObject(i));
                    }
                    rows.add(row);
                }
            }
            return rows.toArray(new String[0][]);
        } catch (SQLException e) {
            throw new IllegalStateException("查询失败: " + e.getMessage(), e);
        }
    }

    static String cellToString(Object v) {
        if (v == null) {
            return null;
        }
        if (v instanceof byte[] bytes) {
            int preview = Math.min(bytes.length, 32);
            String hex = HexFormat.of().formatHex(bytes, 0, preview);
            return bytes.length > preview
                    ? "0x" + hex + "…(" + bytes.length + "B)"
                    : "0x" + hex;
        }
        return v.toString();
    }
}
