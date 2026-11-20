package ofdkit;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * ofd to-text：逐页提取文本与坐标。
 */
final class ToTextCmd {

    private ToTextCmd() {
    }

    static int run(Options o) {
        Path in = Ofd.requireInput(o.singleInput(), "输入文件");
        List<Ofd.PageText> pages = Ofd.extractText(in);

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("input", in.toString());
        res.put("page_count", pages.size());
        List<Map<String, Object>> pageArr = new ArrayList<>();
        int lineCount = 0;
        for (Ofd.PageText page : pages) {
            Map<String, Object> pm = new LinkedHashMap<>();
            pm.put("page", page.page());
            pm.put("size", List.of(page.width(), page.height()));
            List<Map<String, Object>> lines = new ArrayList<>();
            for (Ofd.TextLine line : page.lines()) {
                lines.add(InfoCmd.lineMap(line));
                lineCount++;
            }
            pm.put("lines", lines);
            pageArr.add(pm);
        }
        res.put("pages", pageArr);
        res.put("line_count", lineCount);

        if (o.json) {
            System.out.println(Json.write(res));
            return 0;
        }

        if (pages.isEmpty()) {
            System.out.println("（文档没有页面）");
            return 0;
        }
        for (Ofd.PageText page : pages) {
            System.out.println("== 第 " + page.page() + " / " + pages.size() + " 页  "
                    + Ofd.fmt(page.width()) + "×" + Ofd.fmt(page.height()) + " mm ==");
            if (page.lines().isEmpty()) {
                System.out.println("  （本页无文本层，可能是扫描图像）");
                continue;
            }
            for (Ofd.TextLine line : page.lines()) {
                System.out.println("  " + line.text() + "    [x=" + Ofd.fmt(line.x()) + ", y=" + Ofd.fmt(line.y())
                        + ", w=" + Ofd.fmt(line.w()) + ", h=" + Ofd.fmt(line.h()) + "]");
            }
        }
        return 0;
    }
}
