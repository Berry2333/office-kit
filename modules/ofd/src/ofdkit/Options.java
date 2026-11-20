package ofdkit;

import java.util.ArrayList;
import java.util.List;

/**
 * 命令行参数解析（子命令级）。
 * <p>
 * 支持 {@code --key value} 与 {@code --key=value} 两种写法；{@code --input} 可重复。
 */
final class Options {

    final List<String> inputs = new ArrayList<>();
    String output;
    String outputDir;
    String font;
    String mode;
    int dpi = 144;
    boolean json;
    boolean help;

    private Options() {
    }

    static Options parse(String[] argv) {
        Options o = new Options();
        for (int i = 0; i < argv.length; i++) {
            String arg = argv[i];
            if (arg == null || arg.isEmpty()) {
                continue;
            }
            if ("--json".equals(arg)) {
                o.json = true;
                continue;
            }
            if ("--help".equals(arg) || "-h".equals(arg)) {
                o.help = true;
                continue;
            }
            if (!arg.startsWith("--")) {
                throw new UsageException("无法识别的参数: " + arg + "（参数需以 -- 开头）");
            }
            String key = arg;
            String value = null;
            int eq = arg.indexOf('=');
            if (eq > 0) {
                key = arg.substring(0, eq);
                value = arg.substring(eq + 1);
            }
            switch (key) {
                case "--input", "--output", "--output-dir", "--dpi", "--font", "--mode" -> {
                    if (value == null) {
                        if (i + 1 >= argv.length) {
                            throw new UsageException("参数 " + key + " 缺少取值");
                        }
                        value = argv[++i];
                    }
                    if (value == null || value.isEmpty()) {
                        throw new UsageException("参数 " + key + " 取值为空");
                    }
                    switch (key) {
                        case "--input" -> o.inputs.add(value);
                        case "--output" -> o.output = value;
                        case "--output-dir" -> o.outputDir = value;
                        case "--font" -> o.font = value;
                        case "--mode" -> o.mode = value;
                        case "--dpi" -> o.dpi = parseInt(value);
                        default -> throw new IllegalStateException();
                    }
                }
                default -> throw new UsageException("未知参数: " + key);
            }
        }
        if (o.dpi < 36 || o.dpi > 1200) {
            throw new UsageException("--dpi 必须在 36~1200 之间，当前为 " + o.dpi);
        }
        return o;
    }

    private static int parseInt(String s) {
        try {
            return Integer.parseInt(s.trim());
        } catch (NumberFormatException e) {
            throw new UsageException("--dpi 需要整数，当前为: " + s);
        }
    }

    String singleInput() {
        if (inputs.isEmpty()) {
            throw new UsageException("缺少 --input 参数");
        }
        if (inputs.size() > 1) {
            throw new UsageException("该子命令只接受一个 --input，收到 " + inputs.size() + " 个");
        }
        return inputs.get(0);
    }

    String requireOutput() {
        if (output == null || output.isBlank()) {
            throw new UsageException("缺少 --output 参数");
        }
        return output;
    }

    String requireOutputDir() {
        if (outputDir == null || outputDir.isBlank()) {
            throw new UsageException("缺少 --output-dir 参数");
        }
        return outputDir;
    }

    String requireFont() {
        return font;
    }
}
