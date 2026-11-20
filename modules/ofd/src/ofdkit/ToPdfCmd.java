package ofdkit;

import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.ofdrw.converter.ConvertHelper;

import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * ofd to-pdf：OFD 转 PDF。
 */
final class ToPdfCmd {

    private ToPdfCmd() {
    }

    static int run(Options o) {
        Path in = Ofd.requireInput(o.singleInput(), "输入文件");
        Path out = Ofd.prepareOutputFile(o.requireOutput());
        if (in.equals(out)) {
            throw new OfdException(2, "--output 不能与 --input 相同: " + out);
        }

        int[] pages = {0};
        Ofd.writeAtomically(out, tmp -> {
            try {
                ConvertHelper.toPdf(in, tmp);
            } catch (Exception e) {
                throw new OfdException(1, "OFD 转 PDF 失败: " + Ofd.message(e));
            }
            try (PDDocument doc = Loader.loadPDF(tmp.toFile())) {
                pages[0] = doc.getNumberOfPages();
            }
        });

        long size = Ofd.fileSize(out);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("input", in.toString());
        res.put("output", out.toString());
        res.put("pages", pages[0]);
        res.put("file_size", size);
        res.put("engine", "ofdrw-" + Main.OFDRW_VERSION + "/PDFBox-" + Main.PDFBOX_VERSION);
        if (o.json) {
            System.out.println(Json.write(res));
        } else {
            System.out.println("已生成 PDF: " + out + "（" + pages[0] + " 页, " + Ofd.humanSize(size) + "）");
        }
        return 0;
    }
}
