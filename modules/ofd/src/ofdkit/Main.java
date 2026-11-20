package ofdkit;

import java.io.PrintStream;
import java.util.Arrays;

/**
 * office-kit ofd 模块入口。
 * <p>
 * 用法：ofd &lt;info|to-pdf|to-image|to-text|to-html|merge|from-pdf&gt; [参数...]
 */
public final class Main {

    static final String VERSION = "1.0.0";
    static final String OFDRW_VERSION = "2.5.1";
    static final String PDFBOX_VERSION = "3.0.8";

    public static void main(String[] args) {
        int code;
        try {
            code = run(args);
        } catch (OfdException e) {
            System.err.println("ofd: " + e.getMessage());
            if (e.hint != null) {
                System.err.println("提示: " + e.hint);
            }
            code = e.code;
        } catch (OutOfMemoryError e) {
            System.err.println("ofd: 内存不足。请通过环境变量 OFFICE_KIT_JAVA_OPTS 提高上限，"
                    + "例如 OFFICE_KIT_JAVA_OPTS=\"-Xmx2g\"，或降低 --dpi。");
            code = 1;
        } catch (Throwable t) {
            System.err.println("ofd: 运行时错误: " + Ofd.message(t));
            if (debug()) {
                t.printStackTrace();
            }
            code = 1;
        }
        System.out.flush();
        System.err.flush();
        System.exit(code);
    }

    private static boolean debug() {
        String v = System.getenv("OFD_DEBUG");
        return v != null && !v.isBlank() && !"0".equals(v);
    }

    static int run(String[] argv) throws Exception {
        if (argv.length == 0) {
            help(System.out);
            return 0;
        }
        String cmd = argv[0];
        switch (cmd) {
            case "-h", "--help", "help" -> {
                help(System.out);
                return 0;
            }
            case "-V", "--version", "version" -> {
                System.out.println("ofd " + VERSION + " (ofdrw " + OFDRW_VERSION + ", PDFBox " + PDFBOX_VERSION + ")");
                return 0;
            }
            default -> {
            }
        }
        Options o = Options.parse(Arrays.copyOfRange(argv, 1, argv.length));
        if (o.help) {
            helpFor(cmd, System.out);
            return 0;
        }
        return switch (cmd) {
            case "info" -> InfoCmd.run(o);
            case "to-pdf" -> ToPdfCmd.run(o);
            case "to-image" -> ToImageCmd.run(o);
            case "to-text" -> ToTextCmd.run(o);
            case "to-html" -> ToHtmlCmd.run(o);
            case "merge" -> MergeCmd.run(o);
            case "from-pdf" -> FromPdfCmd.run(o);
            case "demo" -> DemoCmd.run(o);
            default -> throw new UsageException("未知子命令: " + cmd + "（可用: info to-pdf to-image to-text to-html merge from-pdf）");
        };
    }

    static int helpFor(String cmd, PrintStream out) {
        switch (cmd) {
            case "info" -> out.println("""
                    用法: ofd info --input F [--json]

                    读取 OFD 元信息：格式版本、页数、每页尺寸（mm）、文档 ID、签名、
                    字体（是否内嵌）、文本块数量、附件数量。

                    示例:
                      ofd info --input 发票.ofd
                      ofd info --input 发票.ofd --json""");
            case "to-pdf" -> out.println("""
                    用法: ofd to-pdf --input F --output F [--json]

                    将 OFD 转为 PDF（基于 ofdrw PDFBox 渲染管线，内嵌字体会随之写入 PDF）。
                    --output 的父目录会自动创建；输出已存在时会被覆盖。

                    示例:
                      ofd to-pdf --input 公文.ofd --output 公文.pdf
                      ofd to-pdf --input 发票.ofd --output /tmp/发票.pdf --json""");
            case "to-image" -> out.println("""
                    用法: ofd to-image --input F --output-dir D [--dpi 144] [--json]

                    逐页渲染为 PNG（page-001.png、page-002.png ...），默认 144 dpi。
                    --dpi 范围 36~1200；大页面/高 DPI 可用 OFFICE_KIT_JAVA_OPTS=-Xmx2g 扩内存。

                    示例:
                      ofd to-image --input 证照.ofd --output-dir out/证照
                      ofd to-image --input 发票.ofd --output-dir out --dpi 300 --json""");
            case "to-text" -> out.println("""
                    用法: ofd to-text --input F [--json]

                    提取逐页文本及坐标（单位 mm，坐标为页面左上角起算的文字框）。
                    JSON 结构: {"input":..., "page_count":N, "pages":[{"page":1,
                    "size":[w,h], "lines":[{"text":"...","box":[x,y,w,h],"size":字号}]}]}

                    示例:
                      ofd to-text --input 发票.ofd
                      ofd to-text --input 发票.ofd --json""");
            case "to-html" -> out.println("""
                    用法: ofd to-html --input F --output D [--json]

                    在目录 D 生成 index.html（内联 SVG + 可选中文字图层，单文件自包含，
                    不依赖外部资源）。目录不存在会自动创建。

                    示例:
                      ofd to-html --input 公文.ofd --output out/公文-html
                      ofd to-html --input 发票.ofd --output out/html --json""");
            case "merge" -> out.println("""
                    用法: ofd merge --input A --input B [--input C ...] --output F [--json]

                    按 --input 出现顺序合并多个 OFD（至少 2 个），保留页面顺序与资源/字体/签名引用。
                    输出文件已存在时会被覆盖。

                    示例:
                      ofd merge --input a.ofd --input b.ofd --output ab.ofd
                      ofd merge --input 1.ofd --input 2.ofd --input 3.ofd --output all.ofd --json""");
            case "from-pdf" -> out.println("""
                    用法: ofd from-pdf --input F --output F [--mode auto|text|graphics] [--json]

                    将 PDF 转为 OFD。auto（默认）优先文字对象化（文本可检索、内嵌字体）；
                    若字体无法嵌入，或 ofdrw 产出的文字坐标明显异常，则自动回退图形化
                    （版式保真但文本不可检索）。--mode text 强制文字对象化，
                    --mode graphics 强制图形化。

                    JSON 字段: engine=text-object|text-object-outlined|graphics,
                    text_searchable, mode, fallback_reason（发生回退时）。

                    示例:
                      ofd from-pdf --input 合同.pdf --output 合同.ofd
                      ofd from-pdf --input 发票.pdf --output 发票.ofd --mode graphics --json""");
            case "demo" -> out.println("""
                    用法: ofd demo --output F [--font 字体文件] [--json]   （内部自检命令）

                    生成一个含中文的 2 页演示 OFD，供 test.sh 与技能文档示例使用。

                    示例:
                      ofd demo --output .tmp/demo.ofd""");
            default -> {
                out.println("未知子命令: " + cmd);
                help(out);
            }
        }
        return 0;
    }

    static void help(PrintStream out) {
        out.println("""
                ofd %s — 国产版式文档 OFD 工具（ofdrw %s，完全离线）

                用法: ofd <子命令> [参数...]

                子命令:
                  info       --input F [--json]                          版本/页数/尺寸/文档ID/签名/字体/文本块
                  to-pdf     --input F --output F [--json]               OFD -> PDF
                  to-image   --input F --output-dir D [--dpi 144] [--json]  逐页 PNG（page-001.png）
                  to-text    --input F [--json]                          逐页文本 + 坐标
                  to-html    --input F --output D [--json]               OFD -> 自包含 HTML（index.html）
                  merge      --input A --input B [--input C] --output F [--json]  合并
                  from-pdf   --input F --output F [--json]               PDF -> OFD（文字对象化，失败回退图形化）

                通用参数:
                  --json    输出单个 JSON 对象到 stdout（中文不转义）
                  --help    显示子命令帮助
                  -V, --version  版本信息

                环境变量:
                  OFFICE_KIT_JAVA         Java 可执行文件（默认 $OFFICE_KIT_RUNTIME/jre/bin/java）
                  OFFICE_KIT_JAVA_OPTS    JVM 参数，默认 "-Xmx1g"，渲染大图时可设为 "-Xmx2g"
                  OFFICE_KIT_CACHE        临时目录根（默认 ${XDG_CACHE_HOME:-~/.cache}/office-kit）

                退出码: 0 成功；2 参数错误；1 运行时错误；3 缺依赖

                示例:
                  ofd info --input 发票.ofd --json
                  ofd to-pdf --input 公文.ofd --output 公文.pdf
                  ofd to-image --input 证照.ofd --output-dir out --dpi 300
                  ofd to-text --input 发票.ofd
                  ofd merge --input a.ofd --input b.ofd --output ab.ofd
                """.formatted(VERSION, OFDRW_VERSION));
    }

    private Main() {
    }
}
