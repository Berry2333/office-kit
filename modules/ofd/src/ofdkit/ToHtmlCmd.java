package ofdkit;

import org.ofdrw.converter.ConvertHelper;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * ofd to-html：生成自包含 HTML（内联 SVG + 文字图层）。
 */
final class ToHtmlCmd {

    private ToHtmlCmd() {
    }

    static int run(Options o) {
        Path in = Ofd.requireInput(o.singleInput(), "输入文件");
        Path dir = Ofd.prepareOutputDir(o.requireOutput());
        Path index = dir.resolve("index.html");

        try {
            Files.deleteIfExists(index);
        } catch (Exception e) {
            throw new OfdException(1, "无法覆盖已有 index.html: " + index + "（" + Ofd.message(e) + "）");
        }
        int pages = Ofd.pageCount(in);
        try {
            ConvertHelper.toHtml(in, index, 1000);
        } catch (Exception e) {
            throw new OfdException(1, "OFD 转 HTML 失败: " + Ofd.message(e));
        }
        if (!Files.exists(index) || Ofd.fileSize(index) <= 0) {
            throw new OfdException(1, "HTML 生成失败（输出为空）: " + index);
        }
        tidy(index, in.getFileName().toString());

        long size = Ofd.fileSize(index);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("input", in.toString());
        res.put("output_dir", dir.toString());
        res.put("index", index.toString());
        res.put("pages", pages);
        res.put("file_size", size);
        res.put("self_contained", true);
        if (o.json) {
            System.out.println(Json.write(res));
        } else {
            System.out.println("已生成 HTML: " + index + "（" + pages + " 页, " + Ofd.humanSize(size) + "）");
        }
        return 0;
    }

    /**
     * ofdrw 输出的 SVG 内嵌在 HTML 中时带有 XML 声明与 SVG DOCTYPE，
     * 在浏览器里属于无效 HTML；这里做最小清理，并补上中文标题。
     */
    private static void tidy(Path index, String sourceName) {
        try {
            String html = Files.readString(index, StandardCharsets.UTF_8);
            String cleaned = html
                    .replaceAll("(?s)<\\?xml.*?\\?>", "")
                    .replaceAll("(?s)<!DOCTYPE svg.*?>", "")
                    .replace("<html lang=\"en\">", "<html lang=\"zh-CN\">")
                    .replace("<title>文件预览</title>", "<title>" + escapeHtml(sourceName) + " - OFD 预览</title>");
            Files.writeString(index, cleaned, StandardCharsets.UTF_8);
        } catch (Exception e) {
            // 清理失败不影响主产物，保留原始 HTML
            System.err.println("ofd: 提示：HTML 后处理失败（不影响打开）: " + Ofd.message(e));
        }
    }

    private static String escapeHtml(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }
}
