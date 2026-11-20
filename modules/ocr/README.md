# ocr 模块（离线 OCR）

`office-kit ocr` 提供**完全离线**的图片 / PDF 扫描件文字识别，面向麒麟（Kylin V10，
aarch64，glibc 2.31）等无网络环境。默认引擎为 RapidOCR（ONNX Runtime，PP-OCRv4 中英模型），
系统若装有 tesseract 则作为可选后备；不依赖系统 Python、pip、poppler 或任何网络服务。

设计参考 Umi-OCR 的离线思路（RapidOCR 引擎 + 文块/坐标结构 + 版面后处理），但只取识别与
结果结构，不带 Qt 界面（见 `skills/ocr-tools/LICENSES.md`）。

## 目录

```
modules/ocr/
  bin/ocr                 # 入口（bash 包装，exec $OFFICE_KIT_PY lib/ocr_cli.py）
  lib/ocr_cli.py          # 子命令、参数、JSON/文本输出、batch 调度
  lib/ocr_engine.py       # RapidOCR / tesseract 引擎、语言映射、可用性探测
  lib/ocr_io.py           # 图片/PDF 读取、方向矫正、裁切缩放、坐标反算
  lib/ocr_util.py         # 退出码、异常、日志、JSON/文本落盘、临时目录
  lib/models/             # 可选：固化的兜底 ONNX 模型（默认不存在，见下文）
  test.sh                 # 自检（断网、中文 PDF/PNG、坐标/置信度、batch、tesseract）
  README.md
```

## 运行期依赖与来源

全部安装在共享运行时 `runtime/python`（由主智能体统一维护，本模块只读）：

| 包 | 版本 | 用途 | 许可证 |
| --- | --- | --- | --- |
| rapidocr_onnxruntime | 1.4.4 | OCR 引擎（含模型） | Apache-2.0 |
| onnxruntime | 1.32.0 | ONNX 推理 | MIT |
| numpy | 2.5.5 | 数组 | BSD-3-Clause |
| opencv-python-headless | 5.1.0.95 | 图像预处理 | Apache-2.0 |
| pymupdf | 2.1 | PDF 渲染 / 测试数据生成 | AGPL-3.0 |
| pillow | 13.0.0 | 图像读写 | HPND |

安装命令（构建期，已由主智能体执行；运行期**不要**再装）：

```sh
runtime/python/bin/python3 -m pip install --no-cache-dir \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  pymupdf pillow numpy onnxruntime opencv-python-headless rapidocr_onnxruntime
```

> 说明：pypi.org 直连很慢，构建阶段使用了阿里云镜像；运行期不装任何包。
> 本模块没有额外向 `runtime/` 追加文件，也未使用 `--target modules/ocr/lib/py`。

### 模型来源（重点）

RapidOCR 的 PP-OCRv4 模型**随 wheel 内置**，路径为：

```
runtime/python/lib/python3.12/site-packages/rapidocr_onnxruntime/models/
  ch_PP-OCRv4_det_infer.onnx        4.7 MB   文本检测
  ch_PP-OCRv4_rec_infer.onnx       10.8 MB   文本识别（字表写在 ONNX metadata 里）
  ch_ppocr_mobile_v2.0_cls_infer.onnx 0.6 MB 方向分类（0°/180°）
```

运行期**不会**下载模型。验证方式（二选一，test.sh 已包含第 1 种）：

```sh
# 1) 代理指向黑洞，仍能识别
http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 \
  modules/ocr/bin/ocr image --input 扫描.png --engine rapid --json

# 2) 彻底无网络命名空间（需要 unshare 权限）
unshare -rn modules/ocr/bin/ocr image --input 扫描.png --json
```

若目标环境的 wheel 缺模型（例如被裁剪），把上述 3 个 onnx 放到
`modules/ocr/lib/models/`，`ocr_engine.py` 会自动改用它们显式传参（`det_model_path` /
`rec_model_path` / `cls_model_path`），无需改代码。字表可选：有 `ppocr_keys_v1.txt` 时会通过
`rec_keys_path` 传入。

### tesseract（可选后备）

只在系统确实装了 `tesseract`（且有所需 `*.traineddata`）时可用，缺失不影响默认引擎。
除系统 tessdata 外，模块会尝试 `$OFFICE_KIT_STIRLING/tessdata`（随包的 chi_sim/eng/osd），
通过 `--tessdata-dir` 显式指定，避免污染环境变量。语言包缺失时报退出码 3 并给出安装提示。

## 用法

```sh
office-kit ocr image     --input F [--lang chi_sim+eng] [--engine auto|rapid|tess] [--json]
office-kit ocr pdf       --input F [--pages 1-3,5] [--dpi 200] [--lang ...] [--engine ...] [--json]
office-kit ocr batch     --input DIR [--recursive] [--json]
office-kit ocr list-langs [--json]
```

也可直接调用 `modules/ocr/bin/ocr ...`（独立于 `bin/office-kit`，路径自动推导）。

### 公共参数

| 参数 | 说明 |
| --- | --- |
| `--input F` | 输入文件 / 目录；支持中文、空格路径（不要用未加引号的路径） |
| `--lang LANG` | tesseract 风格语言码，`+` 连接，默认 `chi_sim+eng`；`zh`/`chinese`/`en` 等别名自动归一化 |
| `--engine` | `auto`（默认：rapid 优先，缺依赖/不支持该语言时退 tesseract）、`rapid`、`tess` |
| `--json` | stdout 只输出单个 JSON 对象（UTF-8，不转义中文） |
| `--output-json F` | 额外把 JSON 写入文件（父目录自动创建），stdout 仍按 `--json` 与否输出 |
| `--output-text F` | 额外把纯文本写入文件（UTF-8，`\n` 换行） |
| `--rotate` | `auto` / `0` / `90` / `180` / `270`；auto 优先 tesseract OSD，缺失时用 RapidOCR cls 判 0/180 |
| `--region x1,y1,x2,y2` | 只识别指定矩形（原图像素；先按 `--rotate` 摆正再裁切；PDF 对每页生效） |
| `--max-side N` | 长边超过 N 像素先等比缩小再识别，`0`=不缩放（默认 4000） |
| `--quiet` | 不打印人类可读结果（仍可配合 `--output-*` 使用） |

PDF 专属：`--pages SPEC`（`1-3,5`、`3-`、单页 `2`；1-based，越界报 2）、
`--dpi N`（默认 200，范围 36~1200）。batch 专属：`--recursive`、`--output-dir D`
（为每个文件写 `<名字>.json` / `<名字>.txt`）。

### 支持的文件

图片 `.png .jpg .jpeg .bmp .webp .tif .tiff`（多帧 TIFF 取第一帧）、`.pdf`。
batch 只扫描上述扩展名，跳过隐藏文件与其它类型。

## JSON 输出契约

单文件（image / pdf）：

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
      "text": "第一行\n第二行",
      "lines": [
        {"text": "第一行", "box": [166, 229, 594, 284], "score": 0.9953, "page": 1},
        {"text": "第二行", "box": [166, 300, 632, 356], "score": 0.9812, "page": 1}
      ],
      "dpi": 200,
      "pixels_per_point": 2.7778
    }
  ],
  "text": "第一行\n第二行",
  "page_count": 2,
  "dpi": 200,
  "pixels_per_point": 2.7778,
  "stats": {"pages": 1, "lines": 2, "chars": 7},
  "elapsed": 6.2
}
```

* `engine`：`rapid` / `tess`（实际生效的引擎，不是 `auto`）。
* `input`：命令行传入的路径原样回显（不强制绝对路径）。
* `pages[]`：图片固定 1 页；PDF 只包含本次识别的页（`--pages` 过滤后），`page` 是**原始页号**。
* `width`/`height`：基准图像素尺寸。图片＝原图像素（EXIF 已矫正、`--rotate` 摆正后）；
  PDF＝渲染像素。`box` 与该坐标系一致。
* `lines[].box`：轴对齐 `[x1,y1,x2,y2]`，左上原点，整数或 1 位小数。
* `lines[].score`：0~1 置信度（tesseract 的 0~100 已换算）。
* `lines[].page`：该行所属页号。
* `page.text` = 该页 `lines[].text` 用 `\n` 连接；顶层 `text` = 各页 text 用 `\n\n` 连接。
* PDF 页额外带 `dpi` 与 `pixels_per_point`（`dpi/72`），顶层同时给出这两个字段。
* 应用了方向矫正时出现 `page.rotation = {"angle": 180, "method": "osd"}`（图片另在顶层重复一份）；
  `angle` 为**顺时针**旋转角度，`box` 坐标基于摆正后的图。
* 选项生效时的补充字段：无。`--region`/`--max-side` 只影响坐标反算，不额外标记。

batch：

```json
{
  "engine": "rapid",
  "input": "/abs/dir",
  "items": [ { "...": "与单文件结构相同" } ],
  "failures": [ {"input": "/abs/dir/坏文件.png", "error": "无法解码图片：...", "code": 1} ],
  "stats": {"files": 3, "ok": 2, "failed": 1, "pages": 2, "chars": 132},
  "elapsed": 12.5
}
```

单个文件失败不会中断批处理；部分失败时退出码仍为 0，**全部失败**返回 1。
`--output-dir` 用相对 batch 根目录的路径生成文件名（子目录分隔符替换为 `_`）。

`list-langs`：

```json
{
  "default": {"engine": "rapid", "lang": "chi_sim+eng"},
  "engines": {
    "rapid": {"available": true, "version": "1.4.4",
              "languages": ["chi_sim", "chi_tra", "eng"],
              "model_dir": ".../rapidocr_onnxruntime/models", "error": null},
    "tess": {"available": true, "version": "4.1.1",
             "languages": ["chi_sim", "eng", "osd"],
             "system_languages": ["chi_sim", "eng", "osd"],
             "tessdata_dir": null, "tessdata_dirs": [...], "error": null}
  },
  "languages": [{"code": "chi_sim", "name": "简体中文", "engines": ["rapid", "tess"]}]
}
```

## 引擎策略

* `--engine auto`：RapidOCR 可用且语言在 `chi_sim/chi_tra/eng` 内 → rapid；否则 tesseract
  （若可用）；两者都不可用 → 退出码 3，提示安装路径。
* `--engine rapid`：语言超出内置模型能力时报 3，不会静默降级（避免乱码）。
* `--engine tess`：检查语言包，缺包报 3；必要时用 `--tessdata-dir` 指向随包 tessdata。
* `--lang chi_tra`：RapidOCR 的 ch_PP-OCRv4 字表含繁体字，可用但准确率略低于简体。

## 图像处理

1. 读取并转 RGB（EXIF 方向矫正）。
2. `--rotate auto`：tesseract OSD（若系统有）→ 精确到 90°；否则 RapidOCR cls → 只能判 0/180；
   都没有则跳过并打日志（stderr）。
3. `--region` 裁切（摆正后的像素坐标）。
4. 长边 > `--max-side` 等比缩小（LANCZOS）。
5. 引擎识别，坐标按 `base = work / scale + offset` 反算回基准图并裁剪到图内。

## 退出码

| 码 | 含义 | 例子 |
| --- | --- | --- |
| 0 | 成功 | 正常识别；batch 部分失败但至少一个成功 |
| 1 | 运行时错误 | 图片解码失败、PDF 加密/损坏、引擎识别异常、batch 全失败 |
| 2 | 参数错误 | 未知文件类型、缺 `--input`、`--pages` 越界、`--region` 非法、`--dpi` 越界、目录不存在 |
| 3 | 缺依赖 | RapidOCR/tesseract 缺失、语言包缺失、Pillow/PyMuPDF 缺失，均带修复命令 |

错误信息写 stderr；stdout 在 `--json` 下始终是单个 JSON（错误时为空）。

## 测试

```sh
bash modules/ocr/test.sh     # 通过打印 OK ocr
```

覆盖：fitz 内置 CJK 字体生成中文 PDF（不依赖系统字体）→ `ocr pdf` 断言关键字与结构；
导出 PNG → `ocr image` 断言 `lines[].box` 数量/范围与 `score`；`--pages`；断网（代理黑洞）复测；
`list-langs`；中文/空格目录 batch（含坏文件隔离、`--output-dir`）；`--rotate auto`；
系统有 tesseract 时的后备引擎。测试产物在 `.tmp/ocr/test/`，可安全删除。

## 已知限制

* 纯 CPU 推理：A4/200dpi 扫描页约 5~15 秒（视负载），批量时模型只加载一次。
* RapidOCR 内置模型为中英（含繁体字）；日/韩/俄等需 tesseract 语言包，或自行把对应 PP-OCR
  模型放到 `modules/ocr/lib/models/` 并扩展 `ocr_engine.py`。
* 表格/多栏版面只给出行级坐标，不做结构还原；`skills/ocr-tools/scripts/ocr-to-md-table.py`
  提供基于坐标聚类的 Markdown 表格重建思路（启发式）。
* 手写体、低分辨率（<150dpi）、严重倾斜/弯曲页面准确率有限；建议 `--dpi 300` 重渲染并用
  `--rotate auto`。
* 加密 PDF 不尝试解密（请先用 `office-kit pdf run decrypt`）。

## 许可

第三方组件与许可证见 [skills/ocr-tools/LICENSES.md](../../skills/ocr-tools/LICENSES.md)。
特别注意 PyMuPDF 为 AGPL-3.0，本模块仅将其用于 PDF 渲染；如需闭源分发请向主项目确认。
