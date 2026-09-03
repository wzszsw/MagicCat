package com.magiccat.bridge;

import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.SQLException;

/**
 * 服务器/连接信息（M26）：基于标准 JDBC DatabaseMetaData（无方言 SQL）。
 * 返回 JSON：product, productVersion, major, minor, driver, driverVersion,
 * url, user, catalogTerm, schemaTerm, transactionIsolation。
 */
public final class ServerInfoApi {

    private ServerInfoApi() {}

    public static String info(String configId) {
        try (Connection conn = ConnectionRegistry.requirePool(configId).getConnection()) {
            DatabaseMetaData md = conn.getMetaData();
            StringBuilder b = new StringBuilder(256);
            b.append("{")
                    .append("\"product\":").append(Json.q(nz(md.getDatabaseProductName())))
                    .append(",\"productVersion\":").append(Json.q(nz(md.getDatabaseProductVersion())))
                    .append(",\"major\":").append(md.getDatabaseMajorVersion())
                    .append(",\"minor\":").append(md.getDatabaseMinorVersion())
                    .append(",\"driver\":").append(Json.q(nz(md.getDriverName())))
                    .append(",\"driverVersion\":").append(Json.q(nz(md.getDriverVersion())))
                    .append(",\"url\":").append(Json.q(nz(md.getURL())))
                    .append(",\"user\":").append(Json.q(nz(md.getUserName())))
                    .append(",\"catalogTerm\":").append(Json.q(nz(md.getCatalogTerm())))
                    .append(",\"schemaTerm\":").append(Json.q(nz(md.getSchemaTerm())))
                    .append(",\"transactionIsolation\":").append(md.getDefaultTransactionIsolation())
                    .append("}");
            return b.toString();
        } catch (SQLException e) {
            throw new IllegalStateException("读取服务器信息失败: " + e.getMessage(), e);
        }
    }

    private static String nz(String s) {
        return s == null ? "" : s;
    }
}
