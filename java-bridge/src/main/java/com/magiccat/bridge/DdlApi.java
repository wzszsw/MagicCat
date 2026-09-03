package com.magiccat.bridge;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

/** DDL 辅助（M4b）：取服务器原生 DDL（SHOW CREATE TABLE）。 */
public final class DdlApi {

    private DdlApi() {}

    /** 返回 SHOW CREATE TABLE 的第二列（完整建表语句文本）。 */
    public static String showCreateTable(String configId, String schema, String table) {
        String qtable = TableDataApi.quoteIdent(schema) + "." + TableDataApi.quoteIdent(table);
        try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SHOW CREATE TABLE " + qtable)) {
            if (!rs.next()) {
                throw new IllegalStateException("对象不存在: " + schema + "." + table);
            }
            return rs.getString(2);
        } catch (SQLException e) {
            throw new IllegalStateException("读取 DDL 失败: " + e.getMessage(), e);
        }
    }
}
