package ofdkit;

import org.ofdrw.tool.merge.OFDMerger;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * ofd merge：按输入顺序合并多个 OFD。
 */
final class MergeCmd {

    private MergeCmd() {
    }

    static int run(Options o) {
        if (o.inputs.size() < 2) {
            throw new UsageException("merge 至少需要两个 --input（当前 " + o.inputs.size() + " 个）");
        }
        List<Path> inputs = new ArrayList<>();
        for (String raw : o.inputs) {
            inputs.add(Ofd.requireInput(raw, "输入文件"));
        }
        Path out = Ofd.prepareOutputFile(o.requireOutput());
        for (Path p : inputs) {
            if (p.equals(out)) {
                throw new OfdException(2, "输出文件不能与任一输入文件相同: " + out);
            }
        }

        int[] pages = {0};
        Ofd.writeAtomically(out, tmp -> {
            try (OFDMerger merger = new OFDMerger(tmp)) {
                for (Path p : inputs) {
                    merger.add(p);
                }
            } catch (Exception e) {
                throw new OfdException(1, "合并 OFD 失败: " + Ofd.message(e));
            }
            pages[0] = Ofd.pageCount(tmp);
        });

        long size = Ofd.fileSize(out);
        Map<String, Object> res = new LinkedHashMap<>();
        List<String> ins = new ArrayList<>();
        for (Path p : inputs) {
            ins.add(p.toString());
        }
        res.put("inputs", ins);
        res.put("output", out.toString());
        res.put("pages", pages[0]);
        res.put("file_size", size);
        if (o.json) {
            System.out.println(Json.write(res));
        } else {
            System.out.println("已合并 " + inputs.size() + " 个 OFD -> " + out
                    + "（共 " + pages[0] + " 页, " + Ofd.humanSize(size) + "）");
        }
        return 0;
    }
}
