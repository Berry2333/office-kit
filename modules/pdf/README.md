# modules/pdf — 离线 PDF 工具（Stirling-PDF 后端）

本模块把 **Stirling-PDF 3.1.0** 封装成 `office-kit pdf`：按需启动一个 headless JVM 后端，
通过本机 REST API 完成合并、拆分、旋转、加密/解密、水印、压缩、文本抽取、转图片、
图片转 PDF、扫描件 OCR、PDF/A、文档信息等操作。全部离线，不启动 Electron。

## 交付物

```
modules/pdf/
  bin/pdf                 # 可执行入口（bash，定位环境后交给 Python）
  lib/pdfkit.py           # CLI 实现：进程管理 / OpenAPI / multipart / 输出
  lib/icc/sRGB.icc        # PDF/A 兜底所需 sRGB ICC（来自 Ghostscript 色彩配置）
  test.sh                 # 自检脚本（成功打印 OK pdf）
  README.md
skills/pdf-tools/
  SKILL.md                # 中文技能文档
  LICENSES.md             # 上游项目与许可证
```

## 快速开始

```sh
office-kit pdf start
office-kit pdf run merge --input a.pdf --input b.pdf --output ab.pdf
office-kit pdf status --json
office-kit pdf stop
```

首次 `start` 本机实测 **77 秒**（生成 `settings.yml`、初始化 SQLite、JVM 预热；繁忙时可能
到 90-100 秒，文件缓存热时约 22-25 秒），stop 后再次 start **66 秒**（热缓存约 20-25 秒），
已运行时复用 **0.3 秒**。默认就绪超时 **180 秒**，
超时会终止本次拉起的进程并清理 `pid/port/state`，不留孤儿。

## 为什么必须用 bundled glibc loader

`runtime/stirling/native/libjpdfium.so` 等原生库是面向较新发行版构建的：

- 需要 `GLIBC_2.38`、`GLIBCXX_3.4.32`；
- 本机/目标机 Kylin V10 为 **glibc 2.31**，直接 `System.loadLibrary("jpdfium")` 会失败，
  merge/split 等 jpdfium 端点报 `NoClassDefFoundError: JpdfiumLib`。

桌面版 Stirling 自带 `runtime/glibc`（glibc 2.39）。本模块采用与桌面版相同的做法：

```sh
runtime/glibc/lib/ld-linux-aarch64.so.1 \
  --library-path runtime/glibc/lib:runtime/stirling/native:runtime/jre/lib:runtime/jre/lib/server \
  runtime/jre/bin/java ... -Djava.library.path=runtime/stirling/native \
  -jar runtime/stirling/Stirling-PDF.jar
```

另外，fat jar 只内置了 `jpdfium-natives-linux-x64`，没有 arm64；arm64 原生库由
`runtime/stirling/native/` 提供，因此 `-Djava.library.path` 必须指向它。
若 `runtime/glibc` 不存在，入口会回退到直接调用 `java`（在此环境下 jpdfium 工具会不可用）。

## 进程模型

- 后端参数：`-Xmx1536m`（`start --xmx` 可调）、`-Dserver.address=127.0.0.1`、
  `-Dsecurity.enableLogin=false`、`-Dsecurity.csrfDisabled=true`、
  `-DSTIRLING_PDF_TAURI_MODE=true`、日志写入 `<data>/pdf/logs/`。
- 端口：默认从 **8091** 起找空闲端口（`OFFICE_KIT_PDF_PORT` 或 `--port` 可指定）。
  自动选端口时若启动绑定失败（`BindException`/`Address already in use`）会换下一个端口重试，
  最多 5 次；显式 `--port` 被占用则直接报错。
- 就绪判定：轮询 `/api/v1/info/status` 直到 `{"status":"UP"}`；同时解析本次启动日志段落中的
  `running on port: N`，以日志中的真实端口为准（防止端口回退）。
- 状态文件：`$OFFICE_KIT_DATA/pdf/{port,pid,state.json}`；`state.json` 含 pid/port/version/
  started_at/idle_timeout/xmx。
- 并发：`start`/`stop` 用 `flock` 串行化；进程退出后锁自动释放（`start.lock` 文件保留不阻塞）。
- 复用：`start` 发现存活实例会直接复用并返回真实端口；若实例存活但迟迟未就绪，等待超时后
  终止并清理，避免孤儿。
- 端口恢复：`status` 在 `pid` 文件丢失时扫描 `/proc`（匹配本数据目录的
  `-Dlogging.file.path=...`）并从 cmdline/日志恢复端口；`stop` 同样能清理这种孤儿。
- 空闲退出：默认 30 分钟无请求后由后台 watchdog 自动 stop（`start --idle-timeout 0` 关闭；
  `--idle-timeout N` 自定义）。watchdog 通过共享锁避让正在进行的请求。

## 工具名与真实端点

`list-tools` 从运行中实例的 `/v1/api-docs`（OpenAPI 3.0.3）生成并缓存到
`$OFFICE_KIT_DATA/pdf/tools.json`（`schema:2`，按 Stirling 版本失效）。安装/移除
LibreOffice、qpdf 等外部程序后请执行 `list-tools --refresh`，否则缓存里的 `disabled`
标记可能仍是旧状态（`run` 每次都会重新读取启动日志，不受影响）。工具清单里同时给出
友好名、`operationId`、路径、分组、文件/表单/查询字段、输出类型与禁用状态。

固定别名（均来自真实 OpenAPI）：

| 工具 | operationId | REST 路径 |
| --- | --- | --- |
| `merge` | `mergePdfs` | `/api/v1/general/merge-pdfs` |
| `split` | `splitPdf_2` | `/api/v1/general/split-pages` |
| `rotate` | `rotatePDF` | `/api/v1/general/rotate-pdf` |
| `extract-text` | `processPdfToRTForTXT` | `/api/v1/convert/pdf/text` |
| `pdf-to-img` | `convertToImage` | `/api/v1/convert/pdf/img` |
| `img-to-pdf` | `convertToPdf` | `/api/v1/convert/img/pdf` |
| `compress` | `optimizePdf` | `/api/v1/misc/compress-pdf` |
| `encrypt` | `addPassword` | `/api/v1/security/add-password` |
| `decrypt` | `removePassword` | `/api/v1/security/remove-password` |
| `watermark` | `addWatermark` | `/api/v1/security/add-watermark` |
| `ocr` | `processPdfWithOCR` | `/api/v1/misc/ocr-pdf` |
| `pdf-to-pdfa` | `pdfToPdfA` | `/api/v1/convert/pdf/pdfa` |
| `info` | `getBasicInfo` | `/api/v1/analysis/basic-info` |
| `summary` | （组合 4 个 analysis 端点） | `/api/v1/analysis/*` |

其余工具可直接用 `operationId`、路径末段或 `--search` 找到的名字调用。例如：

```sh
office-kit pdf list-tools --search page
office-kit pdf run addPageNumbers --input a.pdf --option position=bottom-center \
  --option fontSize=12 --output a-numbered.pdf
```

## `run` 的通用 REST 行为

- **上传**：`--input` 映射到 schema 的第一个文件字段（通常是 `fileInput`）；数组字段按顺序
  发送多个 part，单文件字段只允许一个输入。附加文件字段用 `--upload 字段名=路径`（如水印图片）。
- **字段**：`--option k=v` 按 OpenAPI 类型处理；数组字段可写 `a+b`/`a,b` 或多个 `--option`；
  schema 的 `default` 会补齐；必填但无默认值的字段缺失时本地报参数错误（退出码 2）。
  `--query k=v` 发送查询参数；未知字段会提示但仍发送（兼容未写入 OpenAPI 的参数）。
- **响应**：PDF/图片直接落盘；ZIP（split、pdf-to-img 多页）写入 `--output x.zip`、
  `--output-dir 目录` 或解压到 `<output>_files/`；文本/JSON 可写入文件，也可直接输出。
- **输出约定**：人类模式只打印输出文件路径；`--json` 输出
  `{ok,tool,outputs,details}`；失败时 `{ok:false,...,error}` + 非 0 退出码，
  stderr 保留后端错误体关键行。密码类字段在 `details.fields` 中显示为 `***`。
- **超时**：`--timeout` 默认 300s，作用于整个请求（包括等待同步处理结果），不是 socket 30s。
- **路径**：完整支持中文与空格（multipart filename 用 UTF-8，内部不经过 shell eval）。

## 本地兜底与外部依赖

### OCR：优先 tesseract，缺失时内置 RapidOCR

- 有系统 `tesseract`：走 Stirling `ocr-pdf` 端点，用 `runtime/stirling/tessdata` 的
  `chi_sim/eng/osd`，输出带可搜索文字层的 PDF。
- 没有 tesseract：**不启动后端**，直接调用 `modules/ocr/bin/ocr pdf --json`（RapidOCR），
  再用 PyMuPDF 把 OCR 行以**不可见文字层**叠加回原页面：
  - `--output *.pdf` → 可搜索 PDF（保持原页面外观）；
  - `--output *.txt/.md` → 纯文本；
  - `--output *.json` → 逐页/逐行结果；
  - 无 `--output` → `--json` 时返回 `details.text`/`details.data`，否则打印文本。
- 结果详情标注 `engine:"rapidocr"`、`fallback:true`。
- 强制引擎：`OFFICE_KIT_PDF_OCR_ENGINE=rapidocr|stirling`（默认 `auto`）。
- 两者都不可用才返回退出码 3。

### PDF/A：系统 Ghostscript

Stirling 的 `pdf-to-pdfa` 端点被 `ExternalAppDepConfig` 归到 LibreOffice 组；本机无
`soffice` 时该端点返回 403 “This endpoint is disabled”。本模块会自动兜底：

```
gs -dPDFA=2 -dPDFACompatibilityPolicy=1 -sColorConversionStrategy=RGB \
   -sDEVICE=pdfwrite -sOutputFile=... PDFA_def.ps input.pdf
```

`sRGB.icc` 在 `lib/icc/`，`PDFA_def.ps` 运行时生成到 `$OFFICE_KIT_CACHE/pdf/`。
输出为 PDF/A-2b（含 XMP `pdfaid:part=2`）。系统没有 `gs` 时退出码 3 并给出安装提示；
**不随包携带 Ghostscript**。

### 依赖矩阵

| 依赖 | 必需？ | 缺失时行为 |
| --- | --- | --- |
| `runtime/jre`、`Stirling-PDF.jar` | 是 | 退出码 3，提示检查 runtime |
| `runtime/glibc` | 事实必需（aarch64） | 回退直接 java；jpdfium 工具失败 |
| 系统 `tesseract` | 否 | 自动走内置 RapidOCR |
| `modules/ocr` | 否 | 无 tesseract 且无它 → OCR 退出码 3 |
| 系统 `gs` | 否（仅 PDF/A） | `pdf-to-pdfa` 退出码 3，提示安装 |
| LibreOffice / qpdf / ImageMagick 等 | 否 | Stirling 会禁用相关端点；`list-tools` 标记 `disabled` |

本机（开发/验收环境）存在 `/usr/bin/tesseract` 4.1.1 与 `/usr/bin/gs` 9.50，因此
`test.sh` 会实际跑 tesseract OCR 与 Ghostscript PDF/A；缺失时对应用例 **SKIP** 而非失败。

## 离线边界

- 后端只绑定 `127.0.0.1`；CLI 的 HTTP 客户端直连 localhost，不读取 `http_proxy`。
- 不下载模型/字体/更新包，不发送遥测；所有处理在本机 JVM、tesseract、RapidOCR、Ghostscript 内。
- `list-tools` 读取本机 OpenAPI；缓存优先（`from_cache:true`）时即使后端未启动也能立即返回。

## 测试

```sh
bash modules/pdf/test.sh        # 成功最后一行：OK pdf（本机约 56 秒）
```

`test.sh` 自行生成测试数据（PyMuPDF，中文 + 空格文件名），覆盖：

- `start` 首次启动、`start` 复用、`status`、`stop` 幂等、未知工具退出码 2；
- `list-tools` 数量与必测工具路径断言；
- merge（5 页）、split（3 个单页）、rotate（90°）、extract-text（中文文本）、
  pdf-to-img（3 张 PNG）、img-to-pdf（2 页）、compress（体积变小）、
  encrypt/decrypt（加密标记 + 解密页数）、watermark（中文水印）、
  ocr（tesseract 或 RapidOCR；断言中文/英文可检索）、pdf-to-pdfa（PDF/A-2 标识）、
  info/summary（页数）；
- 中文与空格路径、`--json` 契约、人类模式输出路径；
- 可选依赖缺失时输出 `SKIP`，不算失败。

断言使用 runtime 的 PyMuPDF 打开输出文件，检查页数/文本/旋转/加密/PNG 尺寸/PDF-A 标记。
测试数据与日志保留在 `.tmp/pdf-test/`，数据目录隔离在 `.tmp/pdf-test/data`，不污染
用户真实的 `$OFFICE_KIT_DATA`。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `OFFICE_KIT_DATA` | 数据根目录；本模块使用其下 `pdf/` |
| `OFFICE_KIT_CACHE` | 缓存根；临时文件在 `pdf/` |
| `OFFICE_KIT_JAVA` / `OFFICE_KIT_STIRLING` / `OFFICE_KIT_RUNTIME` | 运行时定位（有回退） |
| `OFFICE_KIT_PDF_PORT` | 首选端口（默认自动 8091+） |
| `OFFICE_KIT_PDF_OCR_ENGINE` | `auto`（默认）/`stirling`/`rapidocr` |
| `OFFICE_KIT_GS` | 指定 Ghostscript 可执行文件 |
| `OFFICE_KIT_OCR` | 指定 `modules/ocr/bin/ocr` 路径 |
| `OFFICE_KIT_PDF_DEBUG` | 打印 Python 异常栈 |

## 已知限制

- 目标机若既无 tesseract 又无 `modules/ocr`，OCR 不可用；若需要 PDF/A，必须有 Ghostscript。
- PDF/A 兜底是 Ghostscript 的 PDF/A-2b 输出，未跑 veraPDF 全量校验；Stirling 端点自身在
  有 LibreOffice 时才会启用。
- 依赖 LibreOffice/qpdf/ImageMagick 的端点（PDF→Word/HTML/PPT、repair 等）在无相应程序时
  会被禁用；`list-tools` 会显示 `disabled`。
- 内置 OCR 兜底会重建 PDF 页面（保留原页面视觉内容，但书签/表单/注释等结构不保证保留）；
  只做“扫描件 → 可搜索 PDF”用途。
- 大文件会整体读入内存（数十 MB 级正常）；超大文件请用 `--timeout` 并预留内存。
- 仅支持 aarch64 Linux（与 `runtime/` 二进制一致）。

## 许可

上游项目、版本与许可证见 [`skills/pdf-tools/LICENSES.md`](../../skills/pdf-tools/LICENSES.md)。
本模块自身代码可与 office-kit 其他部分一起分发；Stirling-PDF 为 MIT（Open-Core），
其 fat jar 内含 Apache-2.0/BSD 等第三方组件。
