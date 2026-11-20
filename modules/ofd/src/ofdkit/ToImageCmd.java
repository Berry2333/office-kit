package ofdkit;

import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.rendering.ImageType;
import org.apache.pdfbox.rendering.PDFRenderer;
import org.ofdrw.converter.ConvertHelper;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * ofd to-image：逐页渲染 PNG。
 * <p>
 * 先经 ofdrw 转成 PDF（字体/图形处理与 to-pdf 完全一致），再用 PDFBox 按 DPI 栅格化。
 */
final class ToImageCmd {

    private ToImageCmd() {
    }

    static int run(Options o) {
        Path in = Ofd.requireInput(o.singleInput(), "输入文件");
        Path dir = Ofd.prepareOutputDir(o.requireOutputDir());
        int dpi = o.dpi;

        Path tmpPdf = null;
        List<Map<String, Object>> images = new ArrayList<>();
        int pages;
        try {
            tmpPdf = Files.createTempFile("ofd-image-", ".pdf");
            final Path pdf = tmpPdf;
            try {
                ConvertHelper.toPdf(in, pdf);
            } catch (Exception e) {
                throw new OfdException(1, "OFD 转 PDF（图片渲染前置步骤）失败: " + Ofd.message(e));
            }
            try (PDDocument doc = Loader.loadPDF(pdf.toFile())) {
                pages = doc.getNumberOfPages();
                PDFRenderer renderer = new PDFRenderer(doc);
                int digits = Math.max(3, String.valueOf(pages).length());
                for (int i = 0; i < pages; i++) {
                    BufferedImage img;
                    try {
                        img = renderer.renderImageWithDPI(i, dpi, ImageType.RGB);
                    } catch (Exception e) {
                        throw new OfdException(1, "第 " + (i + 1) + " 页渲染失败: " + Ofd.message(e));
                    }
                    String name = String.format("page-%0" + digits + "d.png", i + 1);
                    Path file = dir.resolve(name);
                    boolean ok;
                    try {
                        ok = ImageIO.write(img, "png", file.toFile());
                    } catch (Exception e) {
                        throw new OfdException(1, "写出图片失败: " + file + "（" + Ofd.message(e) + "）");
                    }
                    int w = img.getWidth();
                    int h = img.getHeight();
                    img.flush();
                    if (!ok || !Files.exists(file) || Files.size(file) == 0) {
                        throw new OfdException(1, "图片写出失败或为空: " + file);
                    }
                    Map<String, Object> im = new LinkedHashMap<>();
                    im.put("file", name);
                    im.put("page", i + 1);
                    im.put("width", w);
                    im.put("height", h);
                    images.add(im);
                }
            }
        } catch (OfdException e) {
            throw e;
        } catch (OutOfMemoryError e) {
            throw new OfdException(1, "内存不足，无法渲染图片。请设置 OFFICE_KIT_JAVA_OPTS=\"-Xmx2g\" 或降低 --dpi。");
        } catch (Exception e) {
            throw new OfdException(1, "导出图片失败: " + Ofd.message(e));
        } finally {
            if (tmpPdf != null) {
                try {
                    Files.deleteIfExists(tmpPdf);
                } catch (Exception ignored) {
                    // 临时文件清理失败可忽略
                }
            }
        }

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("input", in.toString());
        res.put("output_dir", dir.toString());
        res.put("dpi", dpi);
        res.put("pages", pages);
        res.put("images", images);
        if (o.json) {
            System.out.println(Json.write(res));
        } else {
            System.out.println("已渲染 " + pages + " 页图片到 " + dir + "（" + dpi + " dpi）");
            for (Map<String, Object> im : images) {
                System.out.println("  " + im.get("file") + "  " + im.get("width") + "×" + im.get("height"));
            }
        }
        return 0;
    }
}
