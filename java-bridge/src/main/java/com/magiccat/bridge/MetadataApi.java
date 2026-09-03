package com.magiccat.bridge;

import java.sql.Connection;
import java.sql.SQLException;

/**
 * 元数据引擎入口（设计方案 §4.2）：按数据库产品自动选择元数据实现。
 *
 * <ul>
 *   <li>MySQL / MariaDB：使用 information_schema —— 实测 mysql-connector-j 的
 *       DatabaseMetaData.getTables(catalog=库) 返回 0、schema 参数又跨库返回全部，
 *       catalog 语义不可靠；且 JDBC 也拿不到完整列类型/EXTRA/触发器。
 *   <li>其它数据库（PostgreSQL / Oracle / SQL Server…）：走 {@link JdbcStandardMetadata}
 *       （标准 DatabaseMetaData，不拼方言 SQL），实现换库零改动。
 * </ul>
 */
public final class MetadataApi {

    private MetadataApi() {}

    private static boolean isMySqlFamily(String configId) {
        try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
            String product = conn.getMetaData().getDatabaseProductName();
            return product != null
                    && (product.toLowerCase().contains("mysql")
                        || product.toLowerCase().contains("mariadb"));
        } catch (SQLException e) {
            throw new IllegalStateException("读取数据库产品失败: " + e.getMessage(), e);
        }
    }

    private static String tablesSql(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT TABLE_NAME AS name, TABLE_TYPE AS type "
                        + "FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? "
                        + "ORDER BY TABLE_TYPE, TABLE_NAME",
                new String[] {schema}, 0);
    }

    private static String routinesSql(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT ROUTINE_NAME AS name, ROUTINE_TYPE AS type "
                        + "FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = ? "
                        + "ORDER BY ROUTINE_TYPE, ROUTINE_NAME",
                new String[] {schema}, 0);
    }

    private static String indexesSql(String configId, String schema, String table) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT INDEX_NAME AS index_name, NON_UNIQUE AS non_unique, "
                        + "SEQ_IN_INDEX AS seq, COLUMN_NAME AS column_name, "
                        + "INDEX_TYPE AS index_type "
                        + "FROM information_schema.STATISTICS "
                        + "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
                        + "ORDER BY INDEX_NAME, SEQ_IN_INDEX",
                new String[] {schema, table}, 0);
    }

    private static String foreignKeysSql(String configId, String schema, String table) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT kcu.CONSTRAINT_NAME AS constraint_name, "
                        + "kcu.COLUMN_NAME AS column_name, "
                        + "kcu.REFERENCED_TABLE_NAME AS ref_table, "
                        + "kcu.REFERENCED_COLUMN_NAME AS ref_column, "
                        + "rc.UPDATE_RULE AS on_update, rc.DELETE_RULE AS on_delete "
                        + "FROM information_schema.KEY_COLUMN_USAGE kcu "
                        + "LEFT JOIN information_schema.REFERENTIAL_CONSTRAINTS rc "
                        + "ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA "
                        + "AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
                        + "WHERE kcu.TABLE_SCHEMA = ? AND kcu.TABLE_NAME = ? "
                        + "AND kcu.REFERENCED_TABLE_NAME IS NOT NULL "
                        + "ORDER BY kcu.CONSTRAINT_NAME, kcu.ORDINAL_POSITION",
                new String[] {schema, table}, 0);
    }

    /** 数据库列表：name。 */
    public static String databases(String configId) {
        if (isMySqlFamily(configId)) {
            return ConnectionRegistry.executeJson(
                    configId,
                    "SELECT SCHEMA_NAME AS name FROM information_schema.SCHEMATA "
                            + "ORDER BY SCHEMA_NAME",
                    null, 0);
        }
        return JdbcStandardMetadata.databases(configId);
    }

    /** 表/视图列表：name, type(BASE TABLE|VIEW)。 */
    public static String tables(String configId, String schema) {
        return isMySqlFamily(configId)
                ? tablesSql(configId, schema)
                : JdbcStandardMetadata.tables(configId, schema);
    }

    /** 存储过程/函数列表：name, type(PROCEDURE|FUNCTION)。 */
    public static String routines(String configId, String schema) {
        return isMySqlFamily(configId)
                ? routinesSql(configId, schema)
                : JdbcStandardMetadata.routines(configId, schema);
    }

    /** 触发器列表：name, event, table。JDBC 无 API → information_schema（仅 MySQL 有意义）。 */
    public static String triggers(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT TRIGGER_NAME AS name, EVENT_MANIPULATION AS event, "
                        + "EVENT_OBJECT_TABLE AS `table` "
                        + "FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = ? "
                        + "ORDER BY TRIGGER_NAME",
                new String[] {schema}, 0);
    }

    /** 列定义（富信息）：name, data_type, nullable, key, default_value, extra, charset,
     *  collation, comment, ordinal。 */
    public static String columns(String configId, String schema, String table) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT COLUMN_NAME AS name, COLUMN_TYPE AS data_type, "
                        + "IS_NULLABLE AS nullable, COLUMN_KEY AS `key`, "
                        + "COLUMN_DEFAULT AS default_value, EXTRA AS extra, "
                        + "CHARACTER_SET_NAME AS charset, COLLATION_NAME AS collation, "
                        + "COLUMN_COMMENT AS comment, ORDINAL_POSITION AS ordinal "
                        + "FROM information_schema.COLUMNS "
                        + "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
                        + "ORDER BY ORDINAL_POSITION",
                new String[] {schema, table}, 0);
    }

    /** 全库列一次批查（避免“逐表循环查列”的 N+1）：额外带 table_name，按表内序排。 */
    public static String schemaColumns(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS name, "
                        + "COLUMN_TYPE AS data_type, IS_NULLABLE AS nullable, "
                        + "COLUMN_KEY AS `key`, COLUMN_DEFAULT AS default_value, "
                        + "EXTRA AS extra, CHARACTER_SET_NAME AS charset, "
                        + "COLLATION_NAME AS collation, COLUMN_COMMENT AS comment, "
                        + "ORDINAL_POSITION AS ordinal FROM information_schema.COLUMNS "
                        + "WHERE TABLE_SCHEMA = ? "
                        + "ORDER BY TABLE_NAME, ORDINAL_POSITION",
                new String[] {schema}, 0);
    }

    /** 全库索引一次批查：额外带 table_name。 */
    public static String schemaIndexes(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT TABLE_NAME AS table_name, INDEX_NAME AS index_name, "
                        + "NON_UNIQUE AS non_unique, SEQ_IN_INDEX AS seq, "
                        + "COLUMN_NAME AS column_name, INDEX_TYPE AS index_type "
                        + "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = ? "
                        + "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
                new String[] {schema}, 0);
    }

    /** 全库外键一次批查：额外带 table_name。 */
    public static String schemaForeignKeys(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT kcu.TABLE_NAME AS table_name, "
                        + "kcu.CONSTRAINT_NAME AS constraint_name, "
                        + "kcu.COLUMN_NAME AS column_name, "
                        + "kcu.REFERENCED_TABLE_NAME AS ref_table, "
                        + "kcu.REFERENCED_COLUMN_NAME AS ref_column, "
                        + "rc.UPDATE_RULE AS on_update, rc.DELETE_RULE AS on_delete "
                        + "FROM information_schema.KEY_COLUMN_USAGE kcu "
                        + "LEFT JOIN information_schema.REFERENTIAL_CONSTRAINTS rc "
                        + "ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA "
                        + "AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
                        + "WHERE kcu.TABLE_SCHEMA = ? "
                        + "AND kcu.REFERENCED_TABLE_NAME IS NOT NULL "
                        + "ORDER BY kcu.TABLE_NAME, kcu.CONSTRAINT_NAME, kcu.ORDINAL_POSITION",
                new String[] {schema}, 0);
    }

    /** 全库表信息一次批查（表对象页用；避免“逐表循环查”的 N+1）：
     *  name, type, engine, rows, data_length, comment。 */
    public static String schemaTables(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT TABLE_NAME AS name, TABLE_TYPE AS type, "
                        + "ENGINE AS engine, TABLE_ROWS AS `rows`, "
                        + "DATA_LENGTH AS data_length, TABLE_COMMENT AS comment "
                        + "FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? "
                        + "ORDER BY TABLE_TYPE, TABLE_NAME",
                new String[] {schema}, 0);
    }

    /** 索引列表：index_name, non_unique, seq, column_name, index_type。 */
    public static String indexes(String configId, String schema, String table) {
        return isMySqlFamily(configId)
                ? indexesSql(configId, schema, table)
                : JdbcStandardMetadata.indexes(configId, schema, table);
    }

    /** 外键列表：constraint_name, column_name, ref_table, ref_column, on_update, on_delete。 */
    public static String foreignKeys(String configId, String schema, String table) {
        return isMySqlFamily(configId)
                ? foreignKeysSql(configId, schema, table)
                : JdbcStandardMetadata.foreignKeys(configId, schema, table);
    }
}
