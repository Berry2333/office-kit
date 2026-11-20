package ofdkit;

import org.ofdrw.font.Font;
import org.ofdrw.layout.OFDDoc;
import org.ofdrw.layout.PageLayout;
import org.ofdrw.layout.VirtualPage;
import org.ofdrw.layout.element.Paragraph;
import org.ofdrw.layout.element.Position;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 内部自检命令：生成一份含中文的 2 页 OFD。
 * <p>
 * 不在对外技能文档中宣传，仅用于 test.sh 与离线环境自检。
 * 优先使用随模块分发的 Noto Sans CJK 子集字体（OFL），保证在其他机器上也能正确显示中文。
 */
final class DemoCmd {

    private DemoCmd() {
    }

    static int run(Options o) {
        Path out = Ofd.prepareOutputFile(o.requireOutput());
        Font font = resolveFont(o);
        boolean embedded = fontFileOf(font) != null;

        int[] pages = {0};
        Ofd.writeAtomically(out, tmp -> {
            try (OFDDoc doc = new OFDDoc(tmp)) {
                doc.setDefaultPageLayout(PageLayout.A4());
                doc.addVPage(page1(font));
                doc.addVPage(page2(font));
            } catch (Exception e) {
                throw new OfdException(1, "生成演示 OFD 失败: " + Ofd.message(e));
            }
            pages[0] = Ofd.pageCount(tmp);
        });

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("output", out.toString());
        res.put("pages", pages[0]);
        res.put("font", embedded ? fontFileOf(font).toString() : "系统默认（未内嵌）");
        res.put("embedded", embedded);
        res.put("file_size", Ofd.fileSize(out));
        if (o.json) {
            System.out.println(Json.write(res));
        } else {
            System.out.println("已生成演示 OFD: " + out + "（" + pages[0] + " 页, "
                    + Ofd.humanSize(Ofd.fileSize(out)) + ", 字体: " + res.get("font") + "）");
        }
        return 0;
    }

    private static VirtualPage page1(Font font) {
        VirtualPage vp = new VirtualPage(PageLayout.A4());
        text(vp, "电子发票（普通发票）", 20, 25, 170, 8, font);
        text(vp, "发票号码：2511200000000001", 20, 40, 170, 4, font);
        text(vp, "开票日期：2026年11月20日", 20, 47, 170, 4, font);
        text(vp, "购买方名称：北京示例科技有限公司", 20, 57, 170, 4, font);
        text(vp, "统一社会信用代码：91110000MA01ABCDEF", 20, 64, 170, 4, font);
        text(vp, "项目名称", 20, 80, 60, 4, font);
        text(vp, "数量", 100, 80, 20, 4, font);
        text(vp, "单价", 125, 80, 25, 4, font);
        text(vp, "金额", 155, 80, 30, 4, font);
        text(vp, "办公文档工具箱", 20, 87, 60, 4, font);
        text(vp, "1", 100, 87, 20, 4, font);
        text(vp, "123.45", 125, 87, 25, 4, font);
        text(vp, "123.45", 155, 87, 30, 4, font);
        text(vp, "价税合计（大写）：壹佰贰拾叁元肆角伍分", 20, 105, 170, 4, font);
        text(vp, "（小写）¥123.45", 20, 112, 170, 4, font);
        text(vp, "备注：office-kit OFD 模块自检样例文档", 20, 125, 170, 4, font);
        text(vp, "测试中文字符：中文不乱码，版式文档 OFD。", 20, 132, 170, 4, font);
        return vp;
    }

    private static VirtualPage page2(Font font) {
        VirtualPage vp = new VirtualPage(PageLayout.A4());
        text(vp, "第二页：合并与多页测试", 20, 30, 170, 7, font);
        text(vp, "本页用于验证页数、合并与逐页文本提取。", 20, 48, 170, 4, font);
        text(vp, "关键词：OFD、发票、公文、证照、ofdrw。", 20, 55, 170, 4, font);
        text(vp, "第二页文本块（用于 to-text 的逐页校验）。", 20, 62, 170, 4, font);
        return vp;
    }

    private static void text(VirtualPage vp, String text, double x, double y, double w, double size, Font font) {
        Paragraph p = new Paragraph(text, size, font);
        p.setPosition(Position.Absolute).setX(x).setY(y).setWidth(w);
        vp.add(p);
    }

    private static Font resolveFont(Options o) {
        List<Path> candidates = new ArrayList<>();
        if (o.font != null) {
            Path p = Ofd.toPath(o.font, "字体文件");
            if (!Files.isRegularFile(p)) {
                throw new OfdException(2, "字体文件不存在: " + p);
            }
            candidates.add(p);
        }
        String env = System.getenv("OFD_DEMO_FONT");
        if (env != null && !env.isBlank()) {
            candidates.add(Paths.get(env));
        }
        Path home = moduleHome();
        if (home != null) {
            candidates.add(home.resolve("testdata/fonts/ofd-demo-cjk.ttf"));
        }
        candidates.add(Paths.get("/usr/share/fonts/gb/国标黑体-GBT2312.ttf"));
        candidates.add(Paths.get("/usr/share/fonts/gb/国标宋体-GBT2312.ttf"));
        candidates.add(Paths.get("/usr/share/fonts/cesi/CESI_HT_GB18030.TTF"));
        candidates.add(Paths.get("/usr/share/fonts/cesi/CESI_SS_GB18030.TTF"));
        candidates.add(Paths.get("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttf"));
        for (Path p : candidates) {
            try {
                if (p != null && Files.isRegularFile(p) && Files.size(p) > 0
                        && !p.getFileName().toString().toLowerCase().endsWith(".ttc")) {
                    String name = "OfficeKit CJK";
                    return new Font(name, name, p);
                }
            } catch (Exception ignored) {
                // 尝试下一个候选
            }
        }
        System.err.println("ofd: 提示：未找到可嵌入的中文字体，演示文档使用系统默认字体，"
                + "在其他机器上可能无法正确显示中文。可用 --font 指定 TTF 字体。");
        return Font.getDefault();
    }

    private static Path fontFileOf(Font font) {
        try {
            return font.getFontFile();
        } catch (NoSuchMethodError | Exception e) {
            return null;
        }
    }

    private static Path moduleHome() {
        String prop = System.getProperty("ofdkit.home");
        if (prop != null && !prop.isBlank()) {
            return Paths.get(prop);
        }
        String root = System.getenv("OFFICE_KIT_ROOT");
        if (root != null && !root.isBlank()) {
            return Paths.get(root, "modules", "ofd");
        }
        return null;
    }
}
