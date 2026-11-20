---
name: ocr-tools
description: 从扫描件、截图、发票、表格照片中离线提取中英混排文字，输出带像素坐标与置信度的 JSON，便于版面重建；支持单图、PDF 指定页与 300dpi 重渲染、批量目录、纯文本 / Markdown 表格导出。触发词：OCR、文字识别、扫描件转文字、发票识别、图片转文本、批量识别。
---

# OCR 工具（office-kit ocr）

用 `office-kit ocr` 做**完全离线**的文字识别：默认 RapidOCR（ONNX，中英混排，模型随包），
系统若有 tesseract 则作为可选后备。输出统一 JSON，带每行文字、像素框、置信度，适合让模型
做版面分析、字段抽取、表格重建。

## 何时使用 / 不适用

**适用**

- 扫描件、手机拍照、截图里的文字提取（中英混排）；
- 发票 / 收据 / 对账单的字段与表格文字提取（需要坐标做版面重建）；
- PDF 扫描件转文本（逐页渲染后识别，不依赖 poppler）；
- 目录批量 OCR，产出逐文件 JSON / TXT；
- 需要每行坐标 + 置信度的下游处理（高亮、裁切、结构化）。

**不适用 / 换工具**

- PDF 本身含文本层（可直接复制）→ 先用 `office-kit pdf run extract-text`，更快更准；
- 需要 PDF 内嵌可搜索文字层（双层 PDF）→ 用 `office-kit pdf run ocr`；
- 手写体、艺术字、严重弯曲/低分辨率（<150dpi）页面：准确率有限，只能尽力；
- 语音转写 → `office-kit asr`；OFD 文本层 → `office-kit ofd to-text`。

## 前置检查

```sh
office-kit --version
office-kit ocr --help
office-kit ocr image --help          # 看全部参数
office-kit ocr list-langs --json     # 确认引擎与语言可用性
```

`list-langs` 里 `engines.rapid.available=true` 表示默认引擎就绪；`engines.tess` 仅作参考，
目标机不一定安装。命令也可直接走 `modules/ocr/bin/ocr ...`（不经过 `office-kit` 包装）。

## 常用示例

> 路径含中文或空格时**必须加引号**。下面命令均已在 `modules/ocr/test.sh` 与手工验证中跑通。

**1）识别单张图片，输出 JSON（带坐标）**

```sh
office-kit ocr image --input "扫描件.png" --json
```

**2）只要纯文本，顺手落盘（quiet 模式不打印识别内容）**

```sh
office-kit ocr image --input "发票.jpg" --output-text "发票.txt" --quiet
```

**3）PDF 指定页 + 提高渲染精度 + 保存 JSON**

```sh
office-kit ocr pdf --input "合同.pdf" --pages 1-3,5 --dpi 300 \
  --json --output-json "合同-ocr.json"
```

**4）批量识别目录（递归子目录），逐文件输出**

```sh
office-kit ocr batch --input "./扫描件" --recursive \
  --json --output-dir "./ocr-结果"
```

**5）只识别局部（发票号码区域），提升小字准确率**

```sh
office-kit ocr image --input "发票.png" --region 120,60,1600,420 --json
```

**6）自动摆正拍歪/倒置的照片**

```sh
office-kit ocr image --input "照片.jpg" --rotate auto --json
```

**7）指定语言 / 换用后备引擎**

```sh
office-kit ocr image --input "英文单据.png" --lang eng --engine rapid --json
office-kit ocr image --input "单据.png" --lang chi_sim+eng --engine tess --json  # 系统有 tesseract 时
```

**8）把带坐标结果重建成 Markdown 表格（发票/对账单）**

```sh
office-kit ocr pdf --input "对账单.pdf" --json --output-json "对账单.json"
"${OFFICE_KIT_PY:-runtime/python/bin/python3}" \
  skills/ocr-tools/scripts/ocr-to-md-table.py "对账单.json"
```

脚本用“行聚类 + 列聚类”的启发式把 `lines[].box` 还原成表格；表头取第一行 ≥2 个单元格的行，
缺列补空。列间距不合适时加 `--gap 60`（像素）微调。

**9）确认能力边界**

```sh
office-kit ocr list-langs --json
```

## 输出解读

单文件（`image` / `pdf`）：

```json
{
  "engine": "rapid",
  "input": "扫描件 中文.pdf",
  "lang": "chi_sim+eng",
  "pages": [
    {
      "page": 1,
      "width": 1653,
      "height": 2339,
      "text": "离线办公 OCR 测试报告\n发票号码: 12345678",
      "lines": [
        {"text": "离线办公 OCR 测试报告", "box": [166, 229, 1120, 284],
         "score": 0.9953, "page": 1}
      ],
      "dpi": 200,
      "pixels_per_point": 2.7778
    }
  ],
  "text": "离线办公 OCR 测试报告\n发票号码: 12345678",
  "page_count": 2,
  "dpi": 200,
  "stats": {"pages": 1, "lines": 7, "chars": 103},
  "elapsed": 6.2
}
```

| 字段 | 含义 / 怎么用 |
| --- | --- |
| `engine` | 实际引擎（`rapid`/`tess`），不是 `auto` |
| `pages[].page` | **原始页号**（`--pages` 过滤后仍保留） |
| `pages[].width/height` | 基准图像素尺寸：图片=原图像素；PDF=渲染像素 |
| `pages[].text` | 该页所有行用 `\n` 连接 |
| `lines[].text` | 一行文字（检测框级，不保证是完整句子） |
| `lines[].box` | `[x1,y1,x2,y2]`，轴对齐、左上原点，与 `width/height` 同坐标系 |
| `lines[].score` | 0~1 置信度；`<0.5` 建议人工复核或重识别 |
| `lines[].page` | 行所属页号 |
| `text` | 各页 `text` 用 `\n\n` 连接 |
| `dpi` / `pixels_per_point` | PDF 渲染参数（`dpi/72`），把像素换算成 PDF point |
| `page.rotation` | 仅应用方向矫正时出现：`{"angle":180,"method":"osd"}`，`box` 基于摆正后的图 |

batch：

```json
{
  "engine": "rapid",
  "items": [ { "...": "同单文件结构" } ],
  "failures": [ {"input": "/dir/坏.png", "error": "无法解码图片", "code": 1} ],
  "stats": {"files": 3, "ok": 2, "failed": 1, "pages": 2, "chars": 132}
}
```

单文件失败不中断批处理；部分失败退出码仍为 0，**全部失败**返回 1，据 `failures` 重试即可。

退出码：`0` 成功、`1` 运行时错误、`2` 参数错误、`3` 缺依赖（stderr 给修复命令）。
`--json` 时 stdout 只有这一个 JSON；进度与诊断在 stderr。

## 准确率提升技巧

1. **PDF 提高 DPI**：默认 200dpi；小字/表格密集页用 `--dpi 300`（400 更慢，收益递减）。
   注意 `box` 是渲染像素，换算回 PDF 坐标要除以 `pixels_per_point`。
2. **裁切小区域**：整页里的小字（发票号码、流水号）用 `--region x1,y1,x2,y2` 只送局部，
   检测器的相对分辨率变高，通常最有效。
3. **先摆正**：`--rotate auto` 用 tesseract OSD（系统有则精确到 90°），否则 RapidOCR cls
   只判 0°/180°；都没有时跳过（stderr 会提示）。
4. **保留分辨率**：默认长边 >4000px 会等比缩小。超高分辨率的小字扫描件可 `--max-side 0`
   或加大数值，代价是更慢。
5. **自己先预处理**：模块只做 RGB 转换、裁切、缩放；去噪/去阴影/二值化可在外部处理后传入，
   往往能显著提升拍照件质量（例如 `pdftoppm`/图片工具的灰度+对比度增强）。
6. **中英混排用默认 `chi_sim+eng`**；纯英文单据 `--lang eng` 偶尔更稳。繁体用 `chi_tra`。
7. **表格重建**：先整页 OCR 保留坐标，再用 `ocr-to-md-table.py` 聚类成列；列错位调 `--gap`，
   或先 `--region` 逐列识别再拼。
8. **按 `score` 复核**：把 `<0.6` 的行挑出来重识别（换 dpi / 裁切 / 换引擎）比整页重跑划算。
9. **引擎选择**：印刷体中英混排优先 `rapid`；纯英文长文或需要其它语种、且系统有 tesseract 时
   试 `--engine tess`；`auto` 会在 rapid 不可用/语言不支持时自动退 tess。

## 常见错误与处理

| 现象 / 退出码 | 原因 | 处理 |
| --- | --- | --- |
| 3，`RapidOCR 不可用` | 运行时缺 rapidocr_onnxruntime / onnxruntime | 构建期装好依赖；运行期离线无法补装，换 `--engine tess` 或联系维护者 |
| 3，`tesseract 未安装` / 缺语言包 | 目标机没有 tesseract 或没有对应 `*.traineddata` | 改 `--engine rapid`；或安装语言包（构建期） |
| 3，`缺少依赖：pillow/pymupdf` | 共享 Python 环境被裁剪 | 构建期补装，运行期无法联网安装 |
| 1，`无法解码图片` | 文件损坏 / 扩展名与内容不符 / 不是图片 | 确认文件；batch 里该文件会进 `failures` |
| 1，`PDF 已加密` | 需要密码 | 先 `office-kit pdf run decrypt --input ... --output ...` |
| 1，`PDF 没有任何页面` / 渲染失败 | 空 PDF 或损坏 | 用 `office-kit pdf run info` 检查源文件 |
| 2，`不支持的文件类型` | 扩展名不在 `.png/.jpg/.jpeg/.bmp/.webp/.tif/.tiff/.pdf` | 转成支持格式；文本类 PDF 先用 extract-text |
| 2，`--pages 越界` / `--region 非法` | 页码或矩形超出范围 | 用 `pdf run info` 看页数；region 用 `x1,y1,x2,y2` 且 x1<x2、y1<y2 |
| 识别出乱码 / 大量缺字 | 分辨率太低、方向不对、语言不匹配 | `--dpi 300`、`--rotate auto`、确认 `--lang`；小字加 `--region` |
| 扫描件识别为空 | 页面本身空白、纯图无文字、或对比度极低 | 检查原图；必要时外部增强对比度 |
| 中文路径报错 | 路径没加引号被 shell 拆分 | 用双引号包住整条路径 |
| batch 部分失败 | 个别文件损坏/加密 | 看 `failures[]`，修复后用 `--input` 单文件重跑 |

## 离线边界

- 识别全程在本机完成：**运行期不联网、不下载模型、不调用系统 pip/apt**。
- 模型随 `rapidocr_onnxruntime` wheel 内置
  （`runtime/python/lib/python3.12/site-packages/rapidocr_onnxruntime/models/`），
  自检会用 `http_proxy=127.0.0.1:9` 黑洞代理复测一遍，证明无网络依赖。
- 首次调用会加载 3 个 ONNX 模型（约 1 秒），批量时只加载一次；A4/200dpi 页面纯 CPU
  约 5~15 秒，属正常。
- tesseract 是可选后备：存在可用、不存在不影响默认能力，**不要假定目标机一定有**。
- 临时文件只写 `$OFFICE_KIT_CACHE/ocr-tmp/`，识别结束即删；结果只写到命令行指定的
  `--output-json` / `--output-text` / `--output-dir`。

## 相关文件

- 模块说明与实现细节：`modules/ocr/README.md`
- 自检脚本：`bash modules/ocr/test.sh`（通过打印 `OK ocr`）
- 表格重建脚本：`skills/ocr-tools/scripts/ocr-to-md-table.py`
- 第三方许可与模型来源：`skills/ocr-tools/LICENSES.md`

## 命令入口（离线机必读）

本技能假设 `office-kit` 已在 `PATH` 中。若执行时报 `command not found`，改用 AppImage 绝对路径：

```sh
KIT="${OFFICE_KIT_BIN:-$HOME/apps/office-kit.AppImage}"
"$KIT" --version
```

后文所有 `office-kit <分组> ...` 都可以等价替换为 `"$KIT" <分组> ...`。
AppImage 需要 `chmod +x`；若提示 FUSE 不可用，加环境变量 `APPIMAGE_EXTRACT_AND_RUN=1`。
