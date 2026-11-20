package ofdkit;

import java.util.Map;

/**
 * 极简 JSON 序列化器。
 * <p>
 * 只服务于本模块 CLI 的 --json 输出：不引入 Jackson 等额外依赖，
 * 支持 Map / Iterable / 数组 / String / Number / Boolean / null，
 * 中文按 UTF-8 原样输出（不做 \\u 转义）。
 */
final class Json {

    private Json() {
    }

    static String write(Object value) {
        StringBuilder sb = new StringBuilder(512);
        append(sb, value);
        return sb.toString();
    }

    private static void append(StringBuilder sb, Object v) {
        if (v == null) {
            sb.append("null");
        } else if (v instanceof String s) {
            quote(sb, s);
        } else if (v instanceof Boolean b) {
            sb.append(b);
        } else if (v instanceof Double || v instanceof Float) {
            number(sb, ((Number) v).doubleValue());
        } else if (v instanceof Number n) {
            sb.append(n);
        } else if (v instanceof Map<?, ?> map) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : map.entrySet()) {
                if (!first) {
                    sb.append(',');
                }
                first = false;
                quote(sb, String.valueOf(e.getKey()));
                sb.append(':');
                append(sb, e.getValue());
            }
            sb.append('}');
        } else if (v instanceof Iterable<?> it) {
            sb.append('[');
            boolean first = true;
            for (Object item : it) {
                if (!first) {
                    sb.append(',');
                }
                first = false;
                append(sb, item);
            }
            sb.append(']');
        } else if (v instanceof Object[] arr) {
            sb.append('[');
            for (int i = 0; i < arr.length; i++) {
                if (i > 0) {
                    sb.append(',');
                }
                append(sb, arr[i]);
            }
            sb.append(']');
        } else {
            quote(sb, String.valueOf(v));
        }
    }

    private static void number(StringBuilder sb, double d) {
        if (Double.isNaN(d) || Double.isInfinite(d)) {
            sb.append("null");
            return;
        }
        if (d == Math.rint(d) && Math.abs(d) < 1e15) {
            sb.append((long) d);
        } else {
            sb.append(Math.round(d * 1000.0) / 1000.0);
        }
    }

    private static void quote(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\b' -> sb.append("\\b");
                case '\f' -> sb.append("\\f");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        sb.append('"');
    }
}
