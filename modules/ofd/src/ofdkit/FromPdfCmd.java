package ofdkit;

import org.ofdrw.converter.ofdconverter.PDFConverter;
import org.ofdrw.converter.ofdconverter.PDFGraphicsConverter;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * ofd from-pdf：PDF 转 OFD。
 * <p>
 * 默认 auto：优先文字对象化（文本可检索）；若字体无法嵌入，或 ofdrw 产出的文字坐标异常，
 * 自动回退图形化（版式保真，文本不可检索）。可用 --mode 强制 text / graphics。
 */
final class FromPdfCmd {

    private static final Set<String> MODES = Set.of("auto", "text", "graphics");

    private FromPdfCmd() {
    }

    static int run(Options o) {
        Path in = Ofd.requireInput(o.singleInput(), "输入 PDF");
        if (!in.getFileName().toString().toLowerCase(Locale.ROOT).endsWith(".pdf")) {
            System.err.println("ofd: 提示：输入文件扩展名不是 .pdf，仍按 PDF 尝试解析。");
        }
        Path out = Ofd.prepareOutputFile(o.requireOutput());
        if (in.equals(out)) {
            throw new OfdException(2, "--output 不能与 --input 相同: " + out);
        }
        String mode = o.mode == null ? "auto" : o.mode;
        if (!MODES.contains(mode)) {
            throw new UsageException("--mode 只能是 auto / text / graphics，当前为: " + mode);
        }

        String[] engine = {"graphics"};
        boolean[] searchable = {false};
        String[] fallback = {null};
        int[] pages = {0};

        Ofd.writeAtomically(out, tmp -> {
            boolean useGraphics = "graphics".equals(mode);
            if (!useGraphics) {
                try {
                    convertText(in, tmp);
                    engine[0] = "PDFConverter";
                    searchable[0] = true;
                } catch (OfdException e) {
                    throw e;
                } catch (Exception e) {
                    if (looksLikePassword(e)) {
                        throw new OfdException(1, "PDF 已加密或受口令保护，无法转换: " + Ofd.message(e));
                    }
                    String firstMsg = Ofd.message(e);
                    if ("text".equals(mode)) {
                        throw new OfdException(1, "PDF 转 OFD（文字对象化）失败: " + firstMsg
                                + "；可改用 --mode graphics 生成版式保真的图形化 OFD。");
                    }
                    deleteQuietly(tmp);
                    System.err.println("ofd: 提示：文字对象化转换失败，回退为图形化 OFD（文本不可检索）。原因: " + firstMsg);
                    fallback[0] = firstMsg;
                    useGraphics = true;
                }
                // ofdrw 2.5.1 的 PDF 文字定位在部分 PDF 上会写出负 DeltaY / 越界边界，
                // 渲染时文字堆叠错位；auto 模式下检测到就回退图形化。
                if (!useGraphics && "auto".equals(mode) && Ofd.hasSuspiciousTextGeometry(tmp)) {
                    deleteQuietly(tmp);
                    System.err.println("ofd: 提示：文字对象化结果的文字坐标异常（ofdrw 2.5.1 PDF 文本定位限制），"
                            + "已回退图形化 OFD（版式保真，文本不可检索）。可用 --mode text 强制保留文字对象。");
                    fallback[0] = "text geometry suspicious";
                    useGraphics = true;
                }
            }
            if (useGraphics) {
                try {
                    convertGraphics(in, tmp);
                } catch (Exception e) {
                    throw new OfdException(1, "PDF 转 OFD 失败: " + Ofd.message(e));
                }
                engine[0] = "PDFGraphicsConverter";
                searchable[0] = false;
            }
            pages[0] = Ofd.pageCount(tmp);
        });

        // 以实际产物为准复核文本可检索性（PDFConverter 在字体无法嵌入时会静默轮廓化）
        if (searchable[0]) {
            try {
                searchable[0] = Ofd.extractText(out).stream().anyMatch(p -> !p.lines().isEmpty());
            } catch (Exception ignored) {
                // 复核失败时保留转换器给出的判断
            }
            if (!searchable[0]) {
                System.err.println("ofd: 提示：转出的 OFD 不含文字对象（文字已转为图形轮廓），文本不可检索。");
            }
        }

        long size = Ofd.fileSize(out);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("input", in.toString());
        res.put("output", out.toString());
        res.put("pages", pages[0]);
        res.put("file_size", size);
        String engineName = "PDFConverter".equals(engine[0])
                ? (searchable[0] ? "text-object" : "text-object-outlined")
                : "graphics";
        res.put("engine", engineName);
        res.put("text_searchable", searchable[0]);
        res.put("mode", mode);
        if (fallback[0] != null) {
            res.put("fallback_reason", fallback[0]);
        }
        if (o.json) {
            System.out.println(Json.write(res));
        } else {
            System.out.println("已生成 OFD: " + out + "（" + pages[0] + " 页, " + Ofd.humanSize(size)
                    + (searchable[0] ? "，文本可检索" : "，图形化（文本不可检索）") + "）");
        }
        return 0;
    }

    private static void convertText(Path in, Path tmp) throws Exception {
        try (PDFConverter converter = new PDFConverter(tmp)) {
            converter.convert(in);
        }
    }

    private static void convertGraphics(Path in, Path tmp) throws Exception {
        try (PDFGraphicsConverter converter = new PDFGraphicsConverter(tmp)) {
            converter.convert(in);
        }
    }

    private static void deleteQuietly(Path p) {
        try {
            Files.deleteIfExists(p);
        } catch (Exception ignored) {
            // 删除失败由后续写入覆盖
        }
    }

    private static boolean looksLikePassword(Throwable t) {
        Throwable cur = t;
        while (cur != null) {
            String name = cur.getClass().getName().toLowerCase(Locale.ROOT);
            String msg = cur.getMessage() == null ? "" : cur.getMessage().toLowerCase(Locale.ROOT);
            if (name.contains("invalidpassword") || msg.contains("password") || msg.contains("encrypt")) {
                return true;
            }
            cur = cur.getCause();
        }
        return false;
    }
}
