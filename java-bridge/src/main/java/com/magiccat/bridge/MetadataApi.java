package com.magiccat.bridge;

/**
 * MySQL 元数据引擎（设计方案 §4.2）：走 information_schema，返回列名对齐的 JSON 表。
 *
 * <p>方法均需 configId 对应连接池已 open。列名即 JSON 键，Python 侧 zip 成 dict。
 */
public final class MetadataApi {

    private MetadataApi() {}

    /** 数据库列表：name。 */
    public static String databases(String configId) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT SCHEMA_NAME AS name FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME",
                null, 0);
    }

    /** 表/视图列表：name, type(BASE TABLE|VIEW)。 */
    public static String tables(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT TABLE_NAME AS name, TABLE_TYPE AS type "
                        + "FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? "
                        + "ORDER BY TABLE_TYPE, TABLE_NAME",
                new String[] {schema}, 0);
    }

    /** 存储过程/函数列表：name, type(PROCEDURE|FUNCTION)。 */
    public static String routines(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT ROUTINE_NAME AS name, ROUTINE_TYPE AS type "
                        + "FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = ? "
                        + "ORDER BY ROUTINE_TYPE, ROUTINE_NAME",
                new String[] {schema}, 0);
    }

    /** 触发器列表：name, event, table。 */
    public static String triggers(String configId, String schema) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT TRIGGER_NAME AS name, EVENT_MANIPULATION AS event, "
                        + "EVENT_OBJECT_TABLE AS `table` "
                        + "FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = ? "
                        + "ORDER BY TRIGGER_NAME",
                new String[] {schema}, 0);
    }

    /** 表/视图列定义：name, data_type, nullable, key, default_value, extra, charset, comment, ordinal。 */
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

    /** 索引列表：index_name, non_unique, seq, column_name, index_type。 */
    public static String indexes(String configId, String schema, String table) {
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

    /** 外键列表：constraint_name, column_name, ref_table, ref_column, on_update, on_delete。 */
    public static String foreignKeys(String configId, String schema, String table) {
        return ConnectionRegistry.executeJson(
                configId,
                "SELECT CONSTRAINT_NAME AS constraint_name, COLUMN_NAME AS column_name, "
                        + "REFERENCED_TABLE_NAME AS ref_table, "
                        + "REFERENCED_COLUMN_NAME AS ref_column, "
                        + "UPDATE_RULE AS on_update, DELETE_RULE AS on_delete "
                        + "FROM information_schema.KEY_COLUMN_USAGE "
                        + "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
                        + "AND REFERENCED_TABLE_NAME IS NOT NULL "
                        + "ORDER BY CONSTRAINT_NAME, ORDINAL_POSITION",
                new String[] {schema, table}, 0);
    }
}
