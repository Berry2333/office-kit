package ofdkit;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * ofd info：读取 OFD 元信息。
 */
final class InfoCmd {

    private InfoCmd() {
    }

    static int run(Options o) {
        Path in = Ofd.requireInput(o.singleInput(), "输入文件");
        Map<String, Object> info = Ofd.describe(in);
        if (o.json) {
            System.out.println(Json.write(info));
            return 0;
        }

        System.out.println("文件      : " + info.get("input") + "  (" + Ofd.humanSize(asLong(info.get("file_size"))) + ")");
        System.out.println("格式版本  : " + info.get("version") + " / " + info.get("doc_type"));
        System.out.println("页数      : " + info.get("pages"));
        System.out.println("页面尺寸  : " + pageSizeText(info));
        System.out.println("文档 ID   : " + emptyDash(info.get("doc_id")));
        String title = String.valueOf(info.get("title"));
        if (!title.isBlank() || !String.valueOf(info.get("author")).isBlank()) {
            System.out.println("标题/作者 : " + emptyDash(title) + " / " + emptyDash(info.get("author")));
        }
        if (!String.valueOf(info.get("creator")).isBlank()) {
            System.out.println("生成工具  : " + info.get("creator") + " " + info.get("creator_version"));
        }
        if (!String.valueOf(info.get("creation_date")).isBlank()) {
            System.out.println("创建日期  : " + info.get("creation_date"));
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> sig = (Map<String, Object>) info.get("signatures");
        long sigCount = asLong(sig.get("count"));
        System.out.println("数字签名  : " + (sigCount == 0 ? "无" : sigCount + " 个 " + sig.get("ids")));

        List<?> fonts = (List<?>) info.get("fonts");
        if (fonts.isEmpty()) {
            System.out.println("字体      : （未声明字体资源）");
        } else {
            List<String> names = new ArrayList<>();
            for (Object item : fonts) {
                @SuppressWarnings("unchecked")
                Map<String, Object> fm = (Map<String, Object>) item;
                names.add(fm.get("name") + (Boolean.TRUE.equals(fm.get("embedded")) ? "(内嵌)" : "(未内嵌)"));
            }
            System.out.println("字体      : " + String.join(", ", names));
        }
        System.out.println("文本块    : " + info.get("text_blocks"));
        System.out.println("附件      : " + info.get("attachments"));
        System.out.println("加密      : " + (Boolean.TRUE.equals(info.get("encrypted")) ? "是" : "否"));
        return 0;
    }

    static Map<String, Object> lineMap(Ofd.TextLine line) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("text", line.text());
        m.put("box", List.of(line.x(), line.y(), line.w(), line.h()));
        m.put("size", line.size());
        return m;
    }

    private static String pageSizeText(Map<String, Object> info) {
        List<?> sizes = (List<?>) info.get("page_sizes");
        if (sizes.isEmpty()) {
            return "未知";
        }
        List<String> parts = new ArrayList<>();
        int limit = Math.min(sizes.size(), 5);
        for (int i = 0; i < limit; i++) {
            List<?> wh = (List<?>) sizes.get(i);
            parts.add(Ofd.fmt(((Number) wh.get(0)).doubleValue()) + "×" + Ofd.fmt(((Number) wh.get(1)).doubleValue()) + " mm");
        }
        if (sizes.size() > limit) {
            parts.add("…（共 " + sizes.size() + " 页）");
        }
        return String.join(", ", parts);
    }

    private static String emptyDash(Object v) {
        String s = v == null ? "" : String.valueOf(v);
        return s.isBlank() ? "—" : s;
    }

    static long asLong(Object v) {
        if (v instanceof Number n) {
            return n.longValue();
        }
        return -1;
    }
}
