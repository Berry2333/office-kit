package ofdkit;

import org.ofdrw.core.basicStructure.ofd.DocBody;
import org.ofdrw.core.basicStructure.ofd.OFD;
import org.ofdrw.core.basicStructure.ofd.docInfo.CT_DocInfo;
import org.ofdrw.core.basicStructure.pageObj.layer.CT_Layer;
import org.ofdrw.core.basicStructure.pageObj.layer.PageBlockType;
import org.ofdrw.core.basicStructure.pageObj.layer.block.CT_PageBlock;
import org.ofdrw.core.basicStructure.pageObj.layer.block.TextObject;
import org.ofdrw.core.basicType.ST_Array;
import org.ofdrw.core.basicType.ST_Box;
import org.ofdrw.core.signatures.Signature;
import org.ofdrw.core.signatures.Signatures;
import org.ofdrw.core.text.TextCode;
import org.ofdrw.core.text.font.CT_Font;
import org.ofdrw.reader.OFDReader;
import org.ofdrw.reader.PageInfo;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * OFD 读取、文本抽取与通用文件辅助。
 */
final class Ofd {

    private Ofd() {
    }

    // ---------------------------------------------------------------- 路径

    static Path requireInput(String raw, String label) {
        if (raw == null || raw.isBlank()) {
            throw new UsageException("缺少 " + label);
        }
        Path p = toPath(raw, label);
        if (!Files.exists(p)) {
            throw new OfdException(2, label + "不存在: " + p);
        }
        if (Files.isDirectory(p)) {
            throw new OfdException(2, label + "是目录而不是文件: " + p);
        }
        if (!Files.isReadable(p)) {
            throw new OfdException(2, label + "不可读（权限不足）: " + p);
        }
        return p;
    }

    static Path toPath(String raw, String label) {
        try {
            return Paths.get(raw).toAbsolutePath().normalize();
        } catch (InvalidPathException e) {
            throw new OfdException(2, label + "路径无效: " + raw + "（" + e.getReason() + "）");
        }
    }

    static Path prepareOutputFile(String raw) {
        if (raw == null || raw.isBlank()) {
            throw new UsageException("缺少 --output 参数");
        }
        Path p = toPath(raw, "输出");
        if (Files.exists(p) && Files.isDirectory(p)) {
            throw new OfdException(2, "输出路径已存在同名目录: " + p);
        }
        return p;
    }

    static Path prepareOutputDir(String raw) {
        if (raw == null || raw.isBlank()) {
            throw new UsageException("缺少输出目录参数");
        }
        Path p = toPath(raw, "输出目录");
        if (Files.exists(p) && !Files.isDirectory(p)) {
            throw new OfdException(2, "输出目录已存在同名文件: " + p);
        }
        try {
            Files.createDirectories(p);
        } catch (IOException e) {
            throw new OfdException(1, "无法创建输出目录: " + p + "（" + e.getMessage() + "）");
        }
        if (!Files.isWritable(p)) {
            throw new OfdException(1, "输出目录不可写: " + p);
        }
        return p;
    }

    /** 先写同目录临时文件，成功后再原子替换，避免失败时留下半个文件。 */
    interface Writer {
        void write(Path tmp) throws Exception;
    }

    static void writeAtomically(Path out, Writer writer) {
        Path parent = out.getParent();
        Path tmp;
        try {
            if (parent != null) {
                Files.createDirectories(parent);
            }
            tmp = Files.createTempFile(parent != null ? parent : Paths.get(".").toAbsolutePath(), ".ofdkit-", ".part");
        } catch (IOException e) {
            throw new OfdException(1, "无法在输出目录创建临时文件: " + out + "（" + e.getMessage() + "）");
        }
        boolean moved = false;
        try {
            writer.write(tmp);
            if (!Files.exists(tmp) || Files.size(tmp) == 0) {
                throw new OfdException(1, "转换未生成有效输出文件: " + out);
            }
            Files.move(tmp, out, StandardCopyOption.REPLACE_EXISTING);
            moved = true;
        } catch (OfdException e) {
            throw e;
        } catch (Exception e) {
            throw new OfdException(1, "写出文件失败: " + out + "（" + message(e) + "）");
        } finally {
            if (!moved) {
                try {
                    Files.deleteIfExists(tmp);
                } catch (IOException ignored) {
                    // 清理失败不影响主错误
                }
            }
        }
    }

    // ---------------------------------------------------------------- OFD 打开

    static void assertZip(Path ofd) {
        try (InputStream in = Files.newInputStream(ofd)) {
            byte[] head = in.readNBytes(4);
            if (head.length < 4 || head[0] != 'P' || head[1] != 'K') {
                throw new OfdException(1, "不是有效的 OFD 文件（缺少 ZIP 容器标识）: " + ofd
                        + "；OFD 是 ZIP 包，请确认文件扩展名与实际格式。");
            }
        } catch (IOException e) {
            throw new OfdException(1, "读取文件失败: " + ofd + "（" + message(e) + "）");
        }
    }

    /** 扫描 ZIP 条目，判断是否含 Encryptions.xml（国密加密容器）。 */
    static boolean isEncrypted(Path ofd) {
        try (ZipFile zf = new ZipFile(ofd.toFile())) {
            Enumeration<? extends ZipEntry> en = zf.entries();
            while (en.hasMoreElements()) {
                String name = en.nextElement().getName();
                if ("Encryptions.xml".equalsIgnoreCase(name) || name.endsWith("/Encryptions.xml")) {
                    return true;
                }
            }
        } catch (IOException ignored) {
            // 交给后续解析报出更具体的错误
        }
        return false;
    }

    static OFDReader open(Path in) {
        assertZip(in);
        if (isEncrypted(in)) {
            throw new OfdException(1, "该 OFD 文档已加密（包含 Encryptions.xml），ofdrw 不支持解密。"
                    + "请用签发系统导出未加密副本后再处理。");
        }
        try {
            return new OFDReader(in);
        } catch (OfdException e) {
            throw e;
        } catch (IOException | RuntimeException e) {
            throw new OfdException(1, "无法解析 OFD 文件（可能已损坏、结构不完整或不是标准 OFD）: "
                    + in + "\n  原因: " + message(e));
        }
    }

    // ---------------------------------------------------------------- 元信息

    static int pageCount(Path ofd) {
        try (OFDReader reader = open(ofd)) {
            return reader.getNumberOfPages();
        } catch (OfdException e) {
            throw e;
        } catch (Exception e) {
            throw new OfdException(1, "读取页数失败: " + ofd + "（" + message(e) + "）");
        }
    }

    static Map<String, Object> describe(Path in) {
        long size;
        try {
            size = Files.size(in);
        } catch (IOException e) {
            size = -1;
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("input", in.toString());
        m.put("file_size", size);
        try (OFDReader reader = open(in)) {
            int pages = reader.getNumberOfPages();
            m.put("pages", pages);
            m.put("page_units", "mm");

            List<List<Double>> sizes = new ArrayList<>();
            for (int i = 1; i <= pages; i++) {
                ST_Box box = reader.getPageSize(i);
                double w = box == null || box.getWidth() == null ? 0 : box.getWidth();
                double h = box == null || box.getHeight() == null ? 0 : box.getHeight();
                sizes.add(List.of(round(w), round(h)));
            }
            m.put("page_sizes", sizes);

            // OFD.xml / Document.xml 元信息
            String version = null;
            String docType = null;
            CT_DocInfo docInfo = null;
            String docId = null;
            List<String> sigIds = new ArrayList<>();
            int sigCount = 0;
            try {
                OFD ofd = reader.getOFDDir().getOfd();
                version = ofd.getVersion();
                docType = ofd.getDocType();
                DocBody body = ofd.getDocBody();
                if (body != null) {
                    docInfo = body.getDocInfo();
                }
                if (docInfo != null) {
                    docId = emptyToNull(docInfo.getDocID());
                }
            } catch (Exception ignored) {
                // 部分第三方 OFD 的 OFD.xml 结构不规范，元信息缺失不影响主体解析
            }
            if (version == null) {
                version = OFD.VERSION;
            }
            m.put("version", version);
            m.put("doc_type", docType == null ? "OFD" : docType);
            m.put("doc_id", docId == null ? "" : docId);
            m.put("title", docInfo == null ? "" : nullToEmpty(docInfo.getTile()));
            m.put("author", docInfo == null ? "" : nullToEmpty(docInfo.getAuthor()));
            m.put("subject", docInfo == null ? "" : nullToEmpty(docInfo.getSubject()));
            m.put("creator", docInfo == null ? "" : nullToEmpty(docInfo.getCreator()));
            m.put("creator_version", docInfo == null ? "" : nullToEmpty(docInfo.getCreatorVersion()));
            m.put("creation_date", docInfo == null || docInfo.getCreationDate() == null
                    ? "" : docInfo.getCreationDate().toString());
            m.put("mod_date", docInfo == null || docInfo.getModDate() == null
                    ? "" : docInfo.getModDate().toString());

            try {
                Signatures signs = reader.getDefaultSignatures();
                if (signs != null && signs.getSignatures() != null) {
                    for (Signature sig : signs.getSignatures()) {
                        sigCount++;
                        String id = sig.getID();
                        if (id != null && !id.isBlank()) {
                            sigIds.add(id);
                        }
                    }
                }
            } catch (Exception ignored) {
                // 签名列表损坏时降级为 0，不影响文档主体
            }
            Map<String, Object> signatures = new LinkedHashMap<>();
            signatures.put("count", sigCount);
            signatures.put("ids", sigIds);
            m.put("signatures", signatures);

            List<Map<String, Object>> fonts = new ArrayList<>();
            try {
                for (CT_Font f : reader.getResMgt().getFonts()) {
                    Map<String, Object> fm = new LinkedHashMap<>();
                    fm.put("name", nullToEmpty(f.getFontName()));
                    fm.put("family", nullToEmpty(f.getFamilyName()));
                    fm.put("embedded", f.getFontFile() != null);
                    fm.put("bold", Boolean.TRUE.equals(f.getBold()));
                    fm.put("italic", Boolean.TRUE.equals(f.getItalic()));
                    fonts.add(fm);
                }
            } catch (Exception ignored) {
                // 资源管理器未加载或资源损坏时返回空字体表
            }
            m.put("fonts", fonts);

            int[] textBlocks = {0};
            for (int i = 1; i <= pages; i++) {
                PageInfo pi = reader.getPageInfo(i);
                walk(pi.getAllLayer(), null, textBlocks);
            }
            m.put("text_blocks", textBlocks[0]);

            int attachments = 0;
            try {
                List<?> list = reader.getAttachmentList();
                attachments = list == null ? 0 : list.size();
            } catch (Exception ignored) {
                // 附件缺失不视为错误
            }
            m.put("attachments", attachments);
            m.put("encrypted", false);
        } catch (OfdException e) {
            throw e;
        } catch (Exception e) {
            throw new OfdException(1, "解析 OFD 结构失败: " + in + "（" + message(e) + "）");
        }
        return m;
    }

    // ---------------------------------------------------------------- 文本

    record TextLine(String text, double x, double y, double w, double h, double size) {
    }

    record PageText(int page, double width, double height, List<TextLine> lines) {
    }

    static List<PageText> extractText(Path in) {
        List<PageText> result = new ArrayList<>();
        try (OFDReader reader = open(in)) {
            int pages = reader.getNumberOfPages();
            for (int i = 1; i <= pages; i++) {
                PageInfo pi = reader.getPageInfo(i);
                ST_Box box = pi.getSize();
                List<TextLine> lines = new ArrayList<>();
                walk(pi.getAllLayer(), lines, null);
                result.add(new PageText(i,
                        box == null || box.getWidth() == null ? 0 : round(box.getWidth()),
                        box == null || box.getHeight() == null ? 0 : round(box.getHeight()),
                        lines));
            }
        } catch (OfdException e) {
            throw e;
        } catch (Exception e) {
            throw new OfdException(1, "提取文本失败: " + in + "（" + message(e) + "）");
        }
        return result;
    }

    /**
     * 递归遍历图层。lines 非空时收集文字行，counter 非空时统计 TextObject 数量。
     */
    private static void walk(List<CT_Layer> layers, List<TextLine> lines, int[] counter) {
        if (layers == null) {
            return;
        }
        for (CT_Layer layer : layers) {
            walkBlocks(layer.getPageBlocks(), lines, counter);
        }
    }

    private static void walkBlocks(List<PageBlockType> blocks, List<TextLine> lines, int[] counter) {
        if (blocks == null) {
            return;
        }
        for (PageBlockType block : blocks) {
            if (block instanceof TextObject text) {
                if (counter != null) {
                    counter[0]++;
                }
                if (lines != null) {
                    collectText(text, lines);
                }
            } else if (block instanceof CT_PageBlock pageBlock) {
                walkBlocks(pageBlock.getPageBlocks(), lines, counter);
            }
        }
    }

    private static void collectText(TextObject obj, List<TextLine> out) {
        ST_Box boundary = obj.getBoundary();
        double bx = boundary == null || boundary.getTopLeftX() == null ? 0 : boundary.getTopLeftX();
        double by = boundary == null || boundary.getTopLeftY() == null ? 0 : boundary.getTopLeftY();
        double bw = boundary == null || boundary.getWidth() == null ? 0 : boundary.getWidth();
        double bh = boundary == null || boundary.getHeight() == null ? 0 : boundary.getHeight();
        Double sizeObj = obj.getSize();
        double fontSize = sizeObj != null && sizeObj > 0 ? sizeObj : (bh > 0 ? bh : 3.5);
        double hScale = obj.getHScale() == null ? 100 : obj.getHScale();

        List<TextCode> codes = obj.getTextCodes();
        if (codes == null || codes.isEmpty()) {
            return;
        }
        for (TextCode code : codes) {
            String text = code.getContent();
            if (text == null || text.isBlank()) {
                continue;
            }
            double cx = code.getX() == null ? 0 : code.getX();
            double cy = code.getY() == null ? 0 : code.getY();
            double width = estimateWidth(code, text, fontSize, hScale);
            if (codes.size() == 1 && bw > 0) {
                // 单个 TextCode 时对象边界通常就是这一行的精确范围
                width = Math.max(width, bw - cx);
            }
            double x = bx + cx;
            double baseline = by + cy;
            double top = cy <= 0 && boundary != null ? by : Math.max(by, baseline - fontSize * 0.88);
            double height = fontSize;
            out.add(new TextLine(text, round(x), round(top), round(width), round(height), round(fontSize)));
        }
    }

    private static double estimateWidth(TextCode code, String text, double fontSize, double hScale) {
        int n = text.codePointCount(0, text.length());
        if (n <= 0) {
            return 0;
        }
        ST_Array dx = code.getDeltaX();
        if (dx != null && dx.size() > 0) {
            Double[] arr;
            try {
                arr = dx.toDouble();
            } catch (RuntimeException e) {
                arr = null;
            }
            if (arr != null && arr.length > 0) {
                double sum = 0;
                for (int i = 0; i < n; i++) {
                    Double d = arr[Math.min(i, arr.length - 1)];
                    sum += Math.abs(d == null ? 0 : d);
                }
                if (sum > 0) {
                    return sum * hScale / 100.0;
                }
            }
        }
        double em = 0;
        for (int i = 0; i < text.length(); ) {
            int cp = text.codePointAt(i);
            i += Character.charCount(cp);
            em += charWidth(cp);
        }
        return em * fontSize * hScale / 100.0;
    }

    private static double charWidth(int cp) {
        if (cp == ' ') {
            return 0.3;
        }
        if (cp < 0x2E80) {
            if ((cp >= '0' && cp <= '9') || (cp >= 'A' && cp <= 'Z') || (cp >= 'a' && cp <= 'z')) {
                return 0.55;
            }
            return 0.45;
        }
        return 1.0;
    }

    /**
     * 检查文字对象几何是否明显异常（用于 from-pdf 的 auto 回退判断）：
     * ofdrw 2.5.1 在部分 PDF 上会写出负 DeltaY（行向上排列）或越界 Boundary，
     * 渲染时文字会堆叠错位。这里只做保守检测，正常 OFD 不会命中。
     */
    static boolean hasSuspiciousTextGeometry(Path ofd) {
        try (OFDReader reader = open(ofd)) {
            int pages = reader.getNumberOfPages();
            for (int i = 1; i <= pages; i++) {
                PageInfo pi = reader.getPageInfo(i);
                ST_Box box = pi.getSize();
                double pw = box == null || box.getWidth() == null ? 0 : box.getWidth();
                double ph = box == null || box.getHeight() == null ? 0 : box.getHeight();
                if (suspiciousLayers(pi.getAllLayer(), pw, ph)) {
                    return true;
                }
            }
        } catch (Exception e) {
            return false;
        }
        return false;
    }

    private static boolean suspiciousLayers(List<CT_Layer> layers, double pw, double ph) {
        if (layers == null) {
            return false;
        }
        for (CT_Layer layer : layers) {
            if (suspiciousBlocks(layer.getPageBlocks(), pw, ph)) {
                return true;
            }
        }
        return false;
    }

    private static boolean suspiciousBlocks(List<PageBlockType> blocks, double pw, double ph) {
        if (blocks == null) {
            return false;
        }
        for (PageBlockType block : blocks) {
            if (block instanceof TextObject text) {
                ST_Box b = text.getBoundary();
                if (b != null) {
                    double x = b.getTopLeftX() == null ? 0 : b.getTopLeftX();
                    double y = b.getTopLeftY() == null ? 0 : b.getTopLeftY();
                    double w = b.getWidth() == null ? 0 : b.getWidth();
                    double h = b.getHeight() == null ? 0 : b.getHeight();
                    if (x < -2 || y < -2) {
                        return true;
                    }
                    if (pw > 0 && x + w > pw + 2) {
                        return true;
                    }
                    if (ph > 0 && y + h > ph + 2) {
                        return true;
                    }
                }
                List<TextCode> codes = text.getTextCodes();
                if (codes != null) {
                    for (TextCode code : codes) {
                        ST_Array dy = code.getDeltaY();
                        if (dy == null || dy.size() == 0) {
                            continue;
                        }
                        try {
                            for (Double v : dy.toDouble()) {
                                if (v != null && v < -0.001) {
                                    return true;
                                }
                            }
                        } catch (RuntimeException ignored) {
                            // 解析失败不视为异常
                        }
                    }
                }
            } else if (block instanceof CT_PageBlock pageBlock) {
                if (suspiciousBlocks(pageBlock.getPageBlocks(), pw, ph)) {
                    return true;
                }
            }
        }
        return false;
    }

    // ---------------------------------------------------------------- 文件辅助

    static String humanSize(long bytes) {
        if (bytes < 0) {
            return "未知";
        }
        if (bytes < 1024) {
            return bytes + " B";
        }
        if (bytes < 1024 * 1024) {
            return String.format(Locale.ROOT, "%.1f KB", bytes / 1024.0);
        }
        return String.format(Locale.ROOT, "%.1f MB", bytes / (1024.0 * 1024.0));
    }

    static long fileSize(Path p) {
        try {
            return Files.size(p);
        } catch (IOException e) {
            return -1;
        }
    }

    static String message(Throwable t) {
        Throwable cur = t;
        String msg = null;
        while (cur != null) {
            if (cur.getMessage() != null && !cur.getMessage().isBlank()) {
                msg = cur.getMessage();
            }
            cur = cur.getCause();
        }
        if (msg == null) {
            msg = t.getClass().getSimpleName();
        }
        return msg.trim().replaceAll("\\s*\\n\\s*", " ");
    }

    static String nullToEmpty(String s) {
        return s == null ? "" : s;
    }

    static String emptyToNull(String s) {
        return s == null || s.isBlank() ? null : s;
    }

    static double round(double v) {
        return Math.round(v * 1000.0) / 1000.0;
    }

    static String fmt(double v) {
        if (v == Math.rint(v)) {
            return String.valueOf((long) v);
        }
        return String.format(Locale.ROOT, "%.2f", v);
    }
}
