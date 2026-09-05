package com.magiccat.bridge;

import java.util.List;

/** 极简 JSON 编码器：跨运行时契约使用（Python 侧 json.loads 解析）。 */
public final class Json {

    private Json() {}

    /** 编码字符串字面量；null -> null。 */
    public static String q(String s) {
        if (s == null) {
            return "null";
        }
        StringBuilder b = new StringBuilder(s.length() + 16);
        b.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> b.append("\\\"");
                case '\\' -> b.append("\\\\");
                case '\n' -> b.append("\\n");
                case '\r' -> b.append("\\r");
                case '\t' -> b.append("\\t");
                case '\b' -> b.append("\\b");
                case '\f' -> b.append("\\f");
                default -> {
                    if (c < 0x20) {
                        b.append(String.format("\\u%04x", (int) c));
                    } else {
                        b.append(c);
                    }
                }
            }
        }
        b.append('"');
        return b.toString();
    }

    /** 主体（不含首尾大括号）："columns":[...],"rows":[[...]]。 */
    private static String body(String[] columns, List<String[]> rows) {
        StringBuilder b = new StringBuilder(256);
        b.append("\"columns\":[");
        for (int i = 0; i < columns.length; i++) {
            if (i > 0) {
                b.append(',');
            }
            b.append(q(columns[i]));
        }
        b.append("],\"rows\":[");
        int r = 0;
        for (String[] row : rows) {
            if (r++ > 0) {
                b.append(',');
            }
            b.append('[');
            for (int i = 0; i < row.length; i++) {
                if (i > 0) {
                    b.append(',');
                }
                b.append(q(row[i]));
            }
            b.append(']');
        }
        b.append("]}");
        return b.toString();
    }

    /** 结果集表：{"columns":[...],"rows":[...]}。 */
    public static String table(String[] columns, List<String[]> rows) {
        return "{" + body(columns, rows);
    }

    /** 查询结果（带 kind=query，供 QueryService 区分）。 */
    public static String queryResult(String[] columns, List<String[]> rows) {
        return "{\"kind\":\"query\"," + body(columns, rows);
    }

    /** 更新结果：{"kind":"update","affected":N}。 */
    public static String updateResult(long affected) {
        return "{\"kind\":\"update\",\"affected\":" + Math.max(affected, 0) + "}";
    }

    /** 表数据页：{total,truncated,sql,pk,kind,columns,rows}。 */
    public static String dataset(String[] columns, List<String[]> rows, long total,
                                 String[] pk, boolean truncated) {
        return dataset(columns, rows, total, pk, truncated, "");
    }

    /** 表数据页（带本次分页执行的 SQL，供状态栏展示）。 */
    public static String dataset(String[] columns, List<String[]> rows, long total,
                                 String[] pk, boolean truncated, String sql) {
        StringBuilder b = new StringBuilder(256);
        b.append("{\"total\":").append(total)
                .append(",\"truncated\":").append(truncated)
                .append(",\"sql\":").append(q(sql))
                .append(",\"pk\":[");
        for (int i = 0; i < pk.length; i++) {
            if (i > 0) {
                b.append(',');
            }
            b.append(q(pk[i]));
        }
        b.append("],\"kind\":\"page\",");
        b.append(body(columns, rows));
        return b.toString();
    }
}
