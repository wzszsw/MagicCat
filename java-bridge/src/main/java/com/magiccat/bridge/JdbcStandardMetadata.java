package com.magiccat.bridge;

import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.TreeMap;

/**
 * 基于标准 JDBC DatabaseMetaData 的元数据提供者（跨数据库产品）。
 *
 * <p>catalog/schema 映射约定（用户已确认的 JDBC 规范）：
 * <ul>
 *   <li>MySQL / MariaDB：database 即 catalog、schema 恒为 null。
 *   <li>PostgreSQL / GaussDB：database 是 catalog，schema 是具体模式；跨库时先连接到
 *       目标 catalog，再调用 DatabaseMetaData。
 * </ul>
 * 行结构刻意与 information_schema 输出一致（列名/取值语义），不波及 Python 侧。
 */
public final class JdbcStandardMetadata {

    /** JDBC 驱动可能将系统库中的真实表报告为 SYSTEM TABLE。 */
    private static final String[] TABLE_TYPES = {"TABLE", "VIEW", "SYSTEM TABLE",
            "MATERIALIZED VIEW"};

    private JdbcStandardMetadata() {}

    private static String catalog(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    // ---- 库/模式列表：name ----
    public static String databases(String configId) {
        List<String[]> rows = new ArrayList<>();
        try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
            // MySQL/MariaDB：database 只映射到 catalog，schema 永远为 null。
            // 不向驱动传入空 catalog：mysql-connector-j 在未选择 database 的连接上
            // 会直接抛出 “Database can not be null”，而 getCatalogs() 本身即可枚举库。
            DatabaseMetaData md = conn.getMetaData();
            Set<String> names = new LinkedHashSet<>();
            try (ResultSet rs = md.getCatalogs()) {
                while (rs.next()) {
                    String cat = rs.getString("TABLE_CAT");
                    if (cat != null && !cat.isBlank()) {
                        names.add(cat);
                    }
                }
            }
            if (names.isEmpty()) {
                // 非 catalog 型数据库（如 PostgreSQL）回退到 schema
                try (ResultSet rs = md.getSchemas()) {
                    while (rs.next()) {
                        String s = rs.getString("TABLE_SCHEM");
                        if (s != null && !s.isBlank()
                                && !s.equalsIgnoreCase("information_schema")
                                && !s.equalsIgnoreCase("pg_catalog")) {
                            names.add(s);
                        }
                    }
                }
            }
            List<String> sorted = new ArrayList<>(names);
            sorted.sort(String.CASE_INSENSITIVE_ORDER);
            for (String n : sorted) {
                rows.add(new String[] {n});
            }
            return Json.table(new String[] {"name"}, rows);
        } catch (SQLException e) {
            throw new IllegalStateException("读取数据库列表失败: " + e.getMessage(), e);
        }
    }

    // ---- 模式列表：name ----
    public static String schemas(String configId, String catalog) {
        String useCatalog = catalog(catalog);
        List<String[]> rows = new ArrayList<>();
        try (Connection conn = ConnectionRegistry.connectionTo(configId, useCatalog)) {
            DatabaseMetaData md = conn.getMetaData();
            try (ResultSet rs = md.getSchemas(useCatalog, "%")) {
                while (rs.next()) {
                    String schema = rs.getString("TABLE_SCHEM");
                    if (schema == null || schema.isBlank()
                            || schema.equalsIgnoreCase("information_schema")
                            || schema.equalsIgnoreCase("pg_catalog")
                            || schema.equalsIgnoreCase("pg_toast")) {
                        continue;
                    }
                    rows.add(new String[] {schema});
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取模式列表失败: " + e.getMessage(), e);
        }
        rows.sort(Comparator.comparing(r -> r[0], String.CASE_INSENSITIVE_ORDER));
        return Json.table(new String[] {"name"}, rows);
    }

    // ---- 列定义（标准 DatabaseMetaData.getColumns）：name, data_type, nullable, key,
    //      default_value, extra, charset, collation, comment, ordinal ----
    public static String columns(String configId, String schema, String table) {
        return columns(configId, "", schema, table);
    }

    /** 列定义；catalog（PG=数据库）可传入以跨库取元数据。 */
    public static String columns(String configId, String catalog, String schema, String table) {
        String useCatalog = catalog(catalog);
        String useSchema = catalog(schema);
        // 收集主键列（用于标记 key=PRI）
        Set<String> pkCols = new LinkedHashSet<>();
        try (Connection conn = ConnectionRegistry.connectionTo(configId, useCatalog)) {
            DatabaseMetaData md = conn.getMetaData();
            try (ResultSet rs = md.getPrimaryKeys(useCatalog, useSchema, table)) {
                while (rs.next()) {
                    pkCols.add(rs.getString("COLUMN_NAME"));
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取主键失败: " + e.getMessage(), e);
        }
        List<String[]> rows = new ArrayList<>();
        try (Connection conn = ConnectionRegistry.connectionTo(configId, useCatalog)) {
            DatabaseMetaData md = conn.getMetaData();
            try (ResultSet rs = md.getColumns(useCatalog, useSchema, table, "%")) {
                while (rs.next()) {
                    String name = rs.getString("COLUMN_NAME");
                    if (name == null) {
                        continue;
                    }
                    String type = columnType(rs);
                    String nullable = nullableFlag(rs);
                    String def = rs.getString("COLUMN_DEF");
                    String extra = "";
                    try {
                        if (autoIncrementFlag(rs)) {
                            extra = "auto_increment";
                        }
                    } catch (SQLException ignore) {
                        // 驱动可能不支持 IS_AUTOINCREMENT 列
                    }
                    String key = pkCols.contains(name) ? "PRI" : "";
                    rows.add(new String[] {name, type, nullable, key, def, extra,
                            "", "", "", String.valueOf(rs.getInt("ORDINAL_POSITION"))});
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取列失败: " + e.getMessage(), e);
        }
        rows.sort(Comparator.comparingInt(r -> Integer.parseInt(r[9])));
        return Json.table(new String[] {"name", "data_type", "nullable", "key",
                "default_value", "extra", "charset", "collation", "comment", "ordinal"}, rows);
    }

    // ---- 表/视图：name, type(BASE TABLE|VIEW) ----
    public static String tables(String configId, String schema) {
        if (ConnectionRegistry.isPostgres(configId)) {
            return tables(configId, "", schema);
        }
        // MySQL/MariaDB 的 database 在 JDBC 中是 catalog，schema 必须传 null。
        return tables(configId, schema, "");
    }

    /** 按 JDBC catalog/schema 获取表和视图。 */
    public static String tables(String configId, String catalog, String schema) {
        String useCatalog = catalog(catalog);
        String useSchema = catalog(schema);
        TreeMap<String, String> byName = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);
        try (Connection conn = ConnectionRegistry.connectionTo(configId, useCatalog)) {
            DatabaseMetaData md = conn.getMetaData();
            addTables(md, useCatalog, useSchema, byName);
        } catch (SQLException e) {
            throw new IllegalStateException("读取表列表失败: " + e.getMessage(), e);
        }
        List<String[]> rows = new ArrayList<>();
        for (String name : byName.keySet()) {
            rows.add(new String[] {name, byName.get(name)});
        }
        rows.sort(Comparator
                .comparing((String[] r) -> r[1])
                .thenComparing(r -> r[0], String.CASE_INSENSITIVE_ORDER));
        return Json.table(new String[] {"name", "type"}, rows);
    }

    /**
     * GaussDB 序列：一次 SQL 返回列表页所需的全部字段。
     *
     * <p>不使用 JDBC 的 SEQUENCE 类型枚举：该接口只能提供名称，无法统一提供
     * 当前值、缓存等属性，而且先枚举再补查会形成两阶段读取。GaussDB 的
     * information_schema.sequences 提供标准字段，按序列 OID 读取的函数补充
     * 当前值和缓存；整个方法只执行一次 PreparedStatement。
     */
    public static String gaussSequences(String configId, String catalog, String schema) {
        String useCatalog = catalog(catalog);
        String useSchema = catalog(schema);
        List<String[]> rows = new ArrayList<>();
        try (Connection conn = ConnectionRegistry.connectionTo(configId, useCatalog)) {
            String sql = "SELECT s.sequence_name AS name, "
                    + "pg_get_userbyid(c.relowner) AS owner, "
                    + "s.increment AS increment, "
                    + "(pg_sequence_last_value(c.oid)).last_value AS last_value, "
                    + "s.minimum_value AS min_value, s.maximum_value AS max_value, "
                    + "s.start_value AS start_value, "
                    + "(pg_sequence_last_value(c.oid)).cache_value AS cache, "
                    + "s.cycle_option AS cycle "
                    + "FROM information_schema.sequences s "
                    + "JOIN pg_catalog.pg_namespace n ON n.nspname = s.sequence_schema "
                    + "JOIN pg_catalog.pg_class c ON c.relnamespace = n.oid "
                    + "AND c.relname = s.sequence_name "
                    + "AND c.relkind IN ('S', 'L') "
                    + "WHERE s.sequence_schema = ? ORDER BY s.sequence_name";
            try (PreparedStatement ps = conn.prepareStatement(sql)) {
                ps.setString(1, useSchema);
                try (ResultSet rs = ps.executeQuery()) {
                    while (rs.next()) {
                        rows.add(new String[] {safeString(rs, "name"), safeString(rs, "owner"),
                                safeString(rs, "increment"), safeString(rs, "last_value"),
                                safeString(rs, "min_value"), safeString(rs, "max_value"),
                                safeString(rs, "start_value"), safeString(rs, "cache"),
                                safeString(rs, "cycle")});
                    }
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取序列列表失败: " + e.getMessage(), e);
        }
        return Json.table(new String[] {"name", "owner", "increment", "last_value",
                "min_value", "max_value", "start_value", "cache", "cycle"}, rows);
    }

    private static void addTables(DatabaseMetaData md, String catalog, String schema,
                                   TreeMap<String, String> byName) throws SQLException {
        try (ResultSet rs = md.getTables(catalog, schema, "%", TABLE_TYPES)) {
            while (rs.next()) {
                String name = rs.getString("TABLE_NAME");
                String type = rs.getString("TABLE_TYPE");
                if (name == null) {
                    continue;
                }
                String normalized = type != null && type.toUpperCase().contains("VIEW")
                        ? "VIEW" : "BASE TABLE";
                byName.putIfAbsent(name, normalized);
            }
        }
    }

    /** 带 JDBC Catalog/Schema 的表对象页批查，富字段不可用时返回空字符串。 */
    public static String schemaTables(String configId, String catalog, String schema) {
        String useCatalog = catalog(catalog);
        String useSchema = catalog(schema);
        TreeMap<String, String[]> byName = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);
        try (Connection conn = ConnectionRegistry.connectionTo(configId, useCatalog)) {
            DatabaseMetaData md = conn.getMetaData();
            try (ResultSet rs = md.getTables(useCatalog, useSchema, "%", TABLE_TYPES)) {
                while (rs.next()) {
                    String name = rs.getString("TABLE_NAME");
                    if (name == null) {
                        continue;
                    }
                    String type = rs.getString("TABLE_TYPE");
                    String normalized = type != null && type.toUpperCase().contains("VIEW")
                            ? "VIEW" : "BASE TABLE";
                    byName.putIfAbsent(name, new String[] {
                            name, normalized, "", "", "", safeString(rs, "REMARKS")});
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取表列表失败: " + e.getMessage(), e);
        }
        List<String[]> rows = new ArrayList<>(byName.values());
        rows.sort(Comparator.comparing((String[] r) -> r[1])
                .thenComparing(r -> r[0], String.CASE_INSENSITIVE_ORDER));
        return Json.table(new String[] {"name", "type", "engine", "rows",
                "data_length", "comment"}, rows);
    }

    /** 带 JDBC Catalog/Schema 的全库列批查。 */
    public static String schemaColumns(String configId, String catalog, String schema) {
        String useCatalog = catalog(catalog);
        String useSchema = catalog(schema);
        List<String[]> rows = new ArrayList<>();
        try (Connection conn = ConnectionRegistry.connectionTo(configId, useCatalog)) {
            DatabaseMetaData md = conn.getMetaData();
            try (ResultSet rs = md.getColumns(useCatalog, useSchema, "%", "%")) {
                while (rs.next()) {
                    String table = rs.getString("TABLE_NAME");
                    String name = rs.getString("COLUMN_NAME");
                    if (table == null || name == null) {
                        continue;
                    }
                    String nullable = nullableFlag(rs);
                    String extra = "";
                    try {
                        if (autoIncrementFlag(rs)) {
                            extra = "auto_increment";
                        }
                    } catch (SQLException ignore) {
                        // 驱动可不提供 IS_AUTOINCREMENT 列
                    }
                    rows.add(new String[] {table, name, safeString(rs, "TYPE_NAME"),
                            nullable, "", safeString(rs, "COLUMN_DEF"), extra,
                            "", "", String.valueOf(rs.getInt("ORDINAL_POSITION"))});
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取列列表失败: " + e.getMessage(), e);
        }
        rows.sort(Comparator.comparing((String[] r) -> r[0], String.CASE_INSENSITIVE_ORDER)
                .thenComparingInt(r -> Integer.parseInt(r[9])));
        return Json.table(new String[] {"table_name", "name", "data_type", "nullable",
                "key", "default_value", "extra", "charset", "collation", "ordinal"}, rows);
    }

    private static String safeString(ResultSet rs, String column) {
        try {
            return rs.getString(column);
        } catch (SQLException e) {
            return "";
        }
    }

    /**
     * 读取 JDBC 列可空标志。
     *
     * <p>标准 JDBC 将 NULLABLE 定义为数字枚举，但 MySQL/MariaDB 驱动在部分
     * 版本中返回信息模式使用的 YES/NO 文本。先按文本读取，再解析数字，避免
     * 对 YES 直接调用 ResultSet#getInt 导致 NumberFormatException。
     */
    private static String nullableFlag(ResultSet rs) throws SQLException {
        String raw = rs.getString("NULLABLE");
        if (raw == null || raw.isBlank()) {
            return "YES";
        }
        String value = raw.trim();
        if ("NO".equalsIgnoreCase(value) || "N".equalsIgnoreCase(value)) {
            return "NO";
        }
        if ("YES".equalsIgnoreCase(value) || "Y".equalsIgnoreCase(value)) {
            return "YES";
        }
        try {
            return Integer.parseInt(value) == DatabaseMetaData.columnNoNulls
                    ? "NO" : "YES";
        } catch (NumberFormatException ignore) {
            // 未知驱动值按可空处理，避免阻断整个表数据页加载。
            return "YES";
        }
    }

    private static boolean autoIncrementFlag(ResultSet rs) throws SQLException {
        String raw = rs.getString("IS_AUTOINCREMENT");
        if (raw == null || raw.isBlank()) {
            return false;
        }
        String value = raw.trim();
        return "YES".equalsIgnoreCase(value)
                || "Y".equalsIgnoreCase(value)
                || "TRUE".equalsIgnoreCase(value)
                || "1".equals(value);
    }

    private static String columnType(ResultSet rs) throws SQLException {
        String type = rs.getString("TYPE_NAME");
        if (type == null || type.isBlank()) {
            return "";
        }
        // JDBC 将长度/精度拆成 COLUMN_SIZE、DECIMAL_DIGITS；恢复常见完整类型，
        // 保证 MySQL 的 varchar(40)/decimal(10,2) 不因切换到标准 API 丢失。
        if (type.contains("(") || !needsSize(type)) {
            return type;
        }
        int size = rs.getInt("COLUMN_SIZE");
        int scale = rs.getInt("DECIMAL_DIGITS");
        if (size <= 0) {
            return type;
        }
        if (isDecimal(type) && scale >= 0) {
            return type + "(" + size + "," + scale + ")";
        }
        return type + "(" + size + ")";
    }

    private static boolean needsSize(String type) {
        String upper = type.toUpperCase();
        return upper.contains("CHAR") || upper.contains("BINARY")
                || upper.contains("DECIMAL") || upper.contains("NUMERIC")
                || upper.equals("FLOAT") || upper.equals("DOUBLE");
    }

    private static boolean isDecimal(String type) {
        String upper = type.toUpperCase();
        return upper.contains("DECIMAL") || upper.contains("NUMERIC");
    }

    // ---- 例程：name, type(PROCEDURE|FUNCTION) ----
    public static String routines(String configId, String schema) {
        TreeMap<String, String> result = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);
        try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
            DatabaseMetaData md = conn.getMetaData();
            try (ResultSet rs = md.getFunctions(null, schema, "%")) {
                while (rs.next()) {
                    String name = rs.getString("FUNCTION_NAME");
                    if (name != null) {
                        result.put(name, "FUNCTION");
                    }
                }
            }
            try (ResultSet rs = md.getProcedures(null, schema, "%")) {
                while (rs.next()) {
                    String name = rs.getString("PROCEDURE_NAME");
                    if (name != null && !result.containsKey(name)) {
                        result.put(name, "PROCEDURE");
                    }
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取例程失败: " + e.getMessage(), e);
        }
        List<String[]> rows = new ArrayList<>();
        for (String name : result.keySet()) {
            rows.add(new String[] {name, result.get(name)});
        }
        rows.sort(Comparator.comparing((String[] r) -> r[1])
                .thenComparing(r -> r[0], String.CASE_INSENSITIVE_ORDER));
        return Json.table(new String[] {"name", "type"}, rows);
    }

    // ---- 索引：index_name, non_unique, seq, column_name, index_type ----
    public static String indexes(String configId, String schema, String table) {
        TreeMap<String, String[]> byKey = new TreeMap<>();
        try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
            DatabaseMetaData md = conn.getMetaData();
            try (ResultSet rs = md.getIndexInfo(null, schema, table, false, false)) {
                while (rs.next()) {
                    String idx = rs.getString("INDEX_NAME");
                    String col = rs.getString("COLUMN_NAME");
                    if (idx == null || col == null) {
                        continue;
                    }
                    short seq = rs.getShort("ORDINAL_POSITION");
                    String nonUnique = rs.getBoolean("NON_UNIQUE") ? "1" : "0";
                    short typeCode = rs.getShort("TYPE");
                    String key = idx + "\u0000" + seq + "\u0000" + col;
                    byKey.putIfAbsent(key, new String[] {
                            idx, nonUnique, String.valueOf(seq), col, indexTypeName(typeCode)});
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取索引失败: " + e.getMessage(), e);
        }
        List<String[]> rows = new ArrayList<>(byKey.values());
        rows.sort(Comparator
                .comparing((String[] r) -> r[0], String.CASE_INSENSITIVE_ORDER)
                .thenComparing(r -> Integer.parseInt(r[2])));
        return Json.table(new String[] {"index_name", "non_unique", "seq",
                "column_name", "index_type"}, rows);
    }

    // ---- 外键：constraint_name, column_name, ref_table, ref_column, on_update, on_delete ----
    public static String foreignKeys(String configId, String schema, String table) {
        TreeMap<String, Object[]> byKey = new TreeMap<>();
        try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
            DatabaseMetaData md = conn.getMetaData();
            try (ResultSet rs = md.getImportedKeys(null, schema, table)) {
                while (rs.next()) {
                    String name = rs.getString("FK_NAME");
                    String key = (name == null ? "" : name) + "\u0000" + rs.getShort("KEY_SEQ");
                    byKey.putIfAbsent(key, new Object[] {
                            name,
                            rs.getString("FKCOLUMN_NAME"),
                            rs.getString("PKTABLE_NAME"),
                            rs.getString("PKCOLUMN_NAME"),
                            shortRuleName(rs.getShort("UPDATE_RULE")),
                            shortRuleName(rs.getShort("DELETE_RULE")),
                            rs.getShort("KEY_SEQ"),
                    });
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取外键失败: " + e.getMessage(), e);
        }
        List<Object[]> all = new ArrayList<>(byKey.values());
        all.sort(Comparator
                .comparing((Object[] r) -> r[0] == null ? "" : (String) r[0],
                        String.CASE_INSENSITIVE_ORDER)
                .thenComparing(r -> (Short) r[6]));
        List<String[]> rows = new ArrayList<>();
        for (Object[] r : all) {
            rows.add(new String[] {(String) r[0], (String) r[1], (String) r[2],
                    (String) r[3], (String) r[4], (String) r[5]});
        }
        return Json.table(new String[] {"constraint_name", "column_name",
                "ref_table", "ref_column", "on_update", "on_delete"}, rows);
    }

    private static String indexTypeName(short code) {
        return switch (code) {
            case DatabaseMetaData.tableIndexHashed -> "HASH";
            case DatabaseMetaData.tableIndexClustered -> "CLUSTERED";
            default -> "";  // other/statistic 无法给出更细信息，交回富信息层
        };
    }

    private static String shortRuleName(short rule) {
        return switch (rule) {
            case DatabaseMetaData.importedKeyCascade -> "CASCADE";
            case DatabaseMetaData.importedKeyRestrict -> "RESTRICT";
            case DatabaseMetaData.importedKeySetNull -> "SET NULL";
            case DatabaseMetaData.importedKeySetDefault -> "SET DEFAULT";
            default -> "NO ACTION";
        };
    }
}
