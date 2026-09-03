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

    /** 编码结果集：{"columns":[...],"rows":[[...]]}，NULL 单元格为 null。 */
    public static String table(String[] columns, List<String[]> rows) {
        StringBuilder b = new StringBuilder(256);
        b.append("{\"columns\":[");
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
}
