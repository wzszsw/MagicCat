package com.magiccat.bridge;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

/**
 * 表数据页 API（M4）：分页读取、主键定位的 UPDATE/DELETE、INSERT。
 *
 * <p>约定：所有值与 SQL 分开绑定（PreparedStatement），列/表名统一反引号转义；
 * where / orderBy 为上层传入的 SQL 片段（面向开发者工具的“筛选/排序”，与编辑器同权限）。
 */
public final class TableDataApi {

    private TableDataApi() {}

    /** 反引号转义标识符。 */
    public static String quoteIdent(String name) {
        return "`" + name.replace("`", "``") + "`";
    }

    /** 分页读表：返回 {columns, rows, total, pk, truncated}。offset 从 0 开始。 */
    public static String page(String configId, String schema, String table,
                              int offset, int limit, String orderBy, String where) {
        String qtable = quoteIdent(schema) + "." + quoteIdent(table);
        String whereClause = (where == null || where.isBlank()) ? " WHERE 1=1" : " WHERE " + where.trim();
        long total;
        List<String[]> rows = new ArrayList<>();
        String[] columns;
        try (Connection conn = requireConnection(configId);
             PreparedStatement countPs = conn.prepareStatement(
                     "SELECT COUNT(*) FROM " + qtable + whereClause);
             ResultSet countRs = countPs.executeQuery()) {
            countRs.next();
            total = countRs.getLong(1);
        } catch (SQLException e) {
            throw new IllegalStateException("统计行数失败: " + e.getMessage(), e);
        }
        String orderSql = (orderBy == null || orderBy.isBlank()) ? "" : " ORDER BY " + orderBy;
        String sql = "SELECT * FROM " + qtable + whereClause + orderSql
                + " LIMIT " + Math.max(offset, 0) + ", " + Math.max(limit, 1);
        try (Connection conn = requireConnection(configId);
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
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
        } catch (SQLException e) {
            throw new IllegalStateException("读取数据失败: " + e.getMessage(), e);
        }
        String[] pk = primaryKey(configId, schema, table);
        return Json.dataset(columns, rows, total, pk, rows.size() >= Math.max(limit, 1));
    }

    /** 主键列（按 ORDINAL_POSITION 排序），无主键返回空数组。 */
    public static String[] primaryKey(String configId, String schema, String table) {
        List<String> pk = new ArrayList<>();
        String sql = "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                + "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND CONSTRAINT_NAME = 'PRIMARY' "
                + "ORDER BY ORDINAL_POSITION";
        try (Connection conn = requireConnection(configId);
             PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setString(1, schema);
            ps.setString(2, table);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    pk.add(rs.getString(1));
                }
            }
        } catch (SQLException e) {
            throw new IllegalStateException("读取主键失败: " + e.getMessage(), e);
        }
        return pk.toArray(new String[0]);
    }

    /** 按主键更新一行；返回受影响行数。vals 中 null 表示 NULL。 */
    public static long updateRow(String configId, String schema, String table,
                                 String[] pkCols, String[] pkVals,
                                 String[] setCols, String[] setVals) {
        if (pkCols == null || pkCols.length == 0) {
            throw new IllegalStateException("该表没有主键，无法安全定位更新");
        }
        if (setCols.length == 0) {
            return 0;
        }
        StringBuilder set = new StringBuilder(" SET ");
        for (int i = 0; i < setCols.length; i++) {
            if (i > 0) {
                set.append(", ");
            }
            set.append(quoteIdent(setCols[i])).append(" = ?");
        }
        StringBuilder where = new StringBuilder(" WHERE ");
        for (int i = 0; i < pkCols.length; i++) {
            if (i > 0) {
                where.append(" AND ");
            }
            where.append(quoteIdent(pkCols[i])).append(" = ?");
        }
        String sql = "UPDATE " + quoteIdent(schema) + "." + quoteIdent(table)
                + set + where;
        try (Connection conn = requireConnection(configId);
             PreparedStatement ps = conn.prepareStatement(sql)) {
            int idx = 1;
            for (String v : setVals) {
                bind(ps, idx++, v);
            }
            for (String v : pkVals) {
                bind(ps, idx++, v);
            }
            return ps.executeUpdate();
        } catch (SQLException e) {
            throw new IllegalStateException("更新失败: " + e.getMessage(), e);
        }
    }

    /** 按主键删除一行。 */
    public static long deleteRow(String configId, String schema, String table,
                                 String[] pkCols, String[] pkVals) {
        if (pkCols == null || pkCols.length == 0) {
            throw new IllegalStateException("该表没有主键，无法安全定位删除");
        }
        StringBuilder where = new StringBuilder(" WHERE ");
        for (int i = 0; i < pkCols.length; i++) {
            if (i > 0) {
                where.append(" AND ");
            }
            where.append(quoteIdent(pkCols[i])).append(" = ?");
        }
        String sql = "DELETE FROM " + quoteIdent(schema) + "." + quoteIdent(table) + where;
        try (Connection conn = requireConnection(configId);
             PreparedStatement ps = conn.prepareStatement(sql)) {
            for (int i = 0; i < pkVals.length; i++) {
                bind(ps, i + 1, pkVals[i]);
            }
            return ps.executeUpdate();
        } catch (SQLException e) {
            throw new IllegalStateException("删除失败: " + e.getMessage(), e);
        }
    }

    /** 插入一行（cols 为空 → INSERT INTO t () VALUES ()，用默认值）。 */
    public static long insertRow(String configId, String schema, String table,
                                 String[] cols, String[] vals) {
        String sql;
        if (cols == null || cols.length == 0) {
            sql = "INSERT INTO " + quoteIdent(schema) + "." + quoteIdent(table) + " () VALUES ()";
        } else {
            StringBuilder names = new StringBuilder();
            StringBuilder marks = new StringBuilder();
            for (int i = 0; i < cols.length; i++) {
                if (i > 0) {
                    names.append(", ");
                    marks.append(", ");
                }
                names.append(quoteIdent(cols[i]));
                marks.append("?");
            }
            sql = "INSERT INTO " + quoteIdent(schema) + "." + quoteIdent(table)
                    + " (" + names + ") VALUES (" + marks + ")";
        }
        try (Connection conn = requireConnection(configId);
             PreparedStatement ps = conn.prepareStatement(sql)) {
            if (cols != null && cols.length > 0) {
                for (int i = 0; i < vals.length; i++) {
                    bind(ps, i + 1, vals[i]);
                }
            }
            return ps.executeUpdate();
        } catch (SQLException e) {
            throw new IllegalStateException("插入失败: " + e.getMessage(), e);
        }
    }

    private static void bind(PreparedStatement ps, int idx, String v) throws SQLException {
        if (v == null) {
            ps.setObject(idx, null);
        } else {
            ps.setObject(idx, v);
        }
    }

    private static Connection requireConnection(String configId) throws SQLException {
        return ConnectionRegistry.requirePool(configId).getConnection();
    }
}
