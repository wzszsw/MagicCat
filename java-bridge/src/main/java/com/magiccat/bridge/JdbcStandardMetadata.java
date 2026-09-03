package com.magiccat.bridge;

import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.TreeMap;

/**
 * 基于标准 JDBC DatabaseMetaData 的元数据提供者（跨库友好，用户要求：少拼方言 SQL）。
 *
 * <p>职责分工（见 docs/MagicCat设计方案.md §4）：
 * - 对象清单/键/外键/索引/例程 —— 一律走 DatabaseMetaData（表/列不存在方言）；
 * - information_schema 仅保留在 JDBC 拿不到的 MySQL 细节上：
 *   完整列类型(COLUMN_TYPE)、字符集/排序、EXTRA、列注释(由列补充层提供)、触发器(无 JDBC API)。
 *
 * 行结构刻意保持与旧 information_schema 实现一致（列名/取值语义），避免波及 Python 侧。
 */
public final class JdbcStandardMetadata {

    private JdbcStandardMetadata() {}

    // ---- 库/模式列表：name ----
    public static String databases(String configId) {
        List<String[]> rows = new ArrayList<>();
        try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
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
                // 非 catalog 型数据库（如多数实现）回退到 schema
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

    // ---- 表/视图：name, type(BASE TABLE|VIEW) ----
    public static String tables(String configId, String schema) {
        // 不同驱动对 catalog/schema 的映射不同：两种参数次序都试并去重
        java.util.Map<String, String> byName = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);
        for (String[] arg : new String[][] {{schema, null}, {null, schema}}) {
            try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
                DatabaseMetaData md = conn.getMetaData();
                try (ResultSet rs = md.getTables(arg[0], arg[1], "%",
                                                 new String[] {"TABLE", "VIEW"})) {
                    while (rs.next()) {
                        String name = rs.getString("TABLE_NAME");
                        String type = rs.getString("TABLE_TYPE");
                        if (name != null) {
                            String normalized = "VIEW".equalsIgnoreCase(type)
                                    ? "VIEW" : "BASE TABLE";
                            byName.putIfAbsent(name, normalized);
                        }
                    }
                }
            } catch (SQLException e) {
                throw new IllegalStateException("读取表列表失败: " + e.getMessage(), e);
            }
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

    // ---- 例程：name, type(PROCEDURE|FUNCTION) ----
    public static String routines(String configId, String schema) {
        TreeMap<String, String> result = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);
        for (String[] arg : new String[][] {{schema, null}, {null, schema}}) {
            try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
                DatabaseMetaData md = conn.getMetaData();
                try (ResultSet rs = md.getFunctions(arg[0], arg[1], "%")) {
                    while (rs.next()) {
                        String name = rs.getString("FUNCTION_NAME");
                        if (name != null) {
                            result.put(name, "FUNCTION");
                        }
                    }
                }
                try (ResultSet rs = md.getProcedures(arg[0], arg[1], "%")) {
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
        for (String[] arg : new String[][] {{schema, null}, {null, schema}}) {
            try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
                DatabaseMetaData md = conn.getMetaData();
                try (ResultSet rs = md.getIndexInfo(arg[0], arg[1], table, false, false)) {
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
                                idx, nonUnique, String.valueOf(seq), col,
                                indexTypeName(typeCode)});
                    }
                }
            } catch (SQLException e) {
                throw new IllegalStateException("读取索引失败: " + e.getMessage(), e);
            }
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
        for (String[] arg : new String[][] {{schema, null}, {null, schema}}) {
            try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
                DatabaseMetaData md = conn.getMetaData();
                try (ResultSet rs = md.getImportedKeys(arg[0], arg[1], table)) {
                    while (rs.next()) {
                        String name = rs.getString("FK_NAME");
                        String key = (name == null ? "" : name) + "\u0000"
                                + rs.getShort("KEY_SEQ");
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
