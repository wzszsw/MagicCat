package com.magiccat.bridge;

import java.sql.Connection;
import java.sql.SQLException;

/**
 * 元数据引擎入口（设计方案 §4.2）：按数据库产品自动选择元数据实现。
 *
 * <ul>
 *   <li>连接、库、模式、表、视图和列的基础元数据统一优先走
 *       {@link JdbcStandardMetadata}（标准 DatabaseMetaData，不拼方言 SQL）。
 *   <li>JDBC 没有覆盖的富字段（MySQL 引擎/估计行数/索引/触发器等）仍由专用查询提供。
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
        // 部分 GaussDB 驱动的 getCatalogs() 只返回当前库；为保证数据库树列出
        // 服务器上的其它可连接数据库，PG/GaussDB 保留标准兼容的 pg_database 查询。
        if (ConnectionRegistry.isPostgres(configId)) {
            return ConnectionRegistry.executeJson(
                    configId,
                    "SELECT datname AS name FROM pg_database "
                            + "WHERE datallowconn ORDER BY datname",
                    null, 0);
        }
        return JdbcStandardMetadata.databases(configId);
    }

    /** 某 database 下的 schema 列表（须临时连到该库）。name */
    public static String schemas(String configId, String database) {
        return JdbcStandardMetadata.schemas(configId, database);
    }

    /** 某 database.schema 下的表/视图（须临时连到该库）。name, type */
    public static String tablesInDatabase(String configId, String database, String schema) {
        return JdbcStandardMetadata.tables(configId, database, schema);
    }

    /** PostgreSQL：某 database.schema 下的例程（函数/过程）。name, type */
    public static String routinesInDatabase(String configId, String database, String schema) {
        return ConnectionRegistry.executeOnDatabase(
                configId, database,
                "SELECT routine_name AS name, routine_type AS type "
                        + "FROM information_schema.routines "
                        + "WHERE routine_schema = ? "
                        + "ORDER BY routine_type, routine_name",
                new String[] {schema}, 0);
    }

    /** PostgreSQL：某 database.schema 下的序列列表（列表页用）。
     *  name, owner, increment, last_value, min_value, max_value, start_value, cache, cycle */
    public static String sequencesInDatabase(String configId, String database, String schema) {
        // openGauss does not expose PostgreSQL's pg_sequences view. The GaussDB
        // implementation uses one information_schema/system-catalog SQL instead
        // of JDBC name enumeration followed by a second enrichment query.
        if (isGaussDb(configId)) {
            return JdbcStandardMetadata.gaussSequences(configId, database, schema);
        }
        return ConnectionRegistry.executeOnDatabase(
                configId, database,
                "SELECT sequencename AS name, sequenceowner AS owner, "
                        + "increment_by AS increment, last_value AS last_value, "
                        + "min_value AS min_value, max_value AS max_value, "
                        + "start_value AS start_value, cache_size AS cache, cycle AS cycle "
                        + "FROM pg_sequences WHERE schemaname = ? ORDER BY sequencename",
                new String[] {schema}, 0);
    }

    private static boolean isGaussDb(String configId) {
        ConnectionRegistry.ConnectParams params = ConnectionRegistry.params(configId);
        return params != null && "gaussdb".equalsIgnoreCase(params.flavor());
    }

    /** 表/视图列表：name, type(BASE TABLE|VIEW)。 */
    public static String tables(String configId, String schema) {
        return JdbcStandardMetadata.tables(configId, schema);
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

    /** 列定义：name, data_type, nullable, key, default_value, extra, charset,
     *  collation, comment, ordinal；基础字段统一来自 JDBC DatabaseMetaData。 */
    public static String columns(String configId, String schema, String table) {
        return columns(configId, "", schema, table);
    }

    /** 列定义；database（PG 的 catalog）传入时对该库取元数据（跨库）。 */
    public static String columns(String configId, String database,
                                 String schema, String table) {
        if (ConnectionRegistry.isPostgres(configId)) {
            return JdbcStandardMetadata.columns(configId, database, schema, table);
        }
        // Python 侧 MySQL 的 schema 参数承载 database 名；JDBC 中映射为 catalog。
        return JdbcStandardMetadata.columns(configId, schema, null, table);
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

    /** 指定 database.schema 下全库列一次批查，供 SQL 上下文补全。 */
    public static String schemaColumnsInDatabase(String configId, String database,
                                                 String schema) {
        return JdbcStandardMetadata.schemaColumns(configId, database, schema);
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

    /** 指定 database.schema 下表/视图一次批查，供 SQL 上下文补全。 */
    public static String schemaTablesInDatabase(String configId, String database,
                                                String schema) {
        return JdbcStandardMetadata.tables(configId, database, schema);
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
