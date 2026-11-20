---
name: pdf-tools
description: 离线 PDF 处理工具（Stirling-PDF 后端）：合并、拆分、旋转、加密/解密、水印、压缩、抽取文本、PDF 转图片、图片转 PDF、扫描件 OCR（中文/英文）、PDF/A、文档信息与摘要。当用户需要合并或拆分 PDF、压缩、加密、加水印、提取文字/图片、把扫描件变成可搜索 PDF、或做 PDF 格式转换时使用。触发词：PDF 合并/拆分/压缩/加密/水印/OCR/转图片/PDF-A。
---

# pdf-tools — 离线 PDF 处理

本技能通过本机后台运行的 **Stirling-PDF 3.1.0**（headless，不启动 Electron）完成 PDF 处理。
所有能力都在本机执行，**不联网**；命令统一为 `office-kit pdf ...`。

## 何时使用

适合：

- 合并多个 PDF/图片；按页码或范围拆分；旋转页面。
- 压缩体积；给 PDF 加打开密码或权限，或移除已知密码。
- 加文字/图片水印、页码、图章。
- 抽取文本层；PDF 转 PNG/JPEG；图片合成 PDF。
- **扫描件 OCR**：给没有文字层的 PDF 加中英文可搜索文本层。
- PDF/A 归档格式转换。
- 查询页数、版本、文档属性、安全信息。

不适合：

- 需要编辑 Word/Excel/PPT 内容 → 用 `office-docs` 技能。
- 只需识别单张图片文字、需要按行/框输出 → 用 `ocr-tools` 技能（RapidOCR）。
- OFD 版式文件 → 用 `ofd-tools`。
- 需要联网的在线转换、需要 Adobe 专有表单脚本等场景 → 不支持。
- 加密 PDF 不知道密码：无法破解，只能先向用户索取密码。

## 前置检查

```sh
office-kit --version
office-kit pdf --help
office-kit pdf status --json
```

如果 `status --json` 返回 `{"running": false}`，执行 `office-kit pdf start`，
或直接运行任意 `pdf run`（会自动拉起后端）。

依赖（权重从高到低）：

- `runtime/jre`（Temurin 25）、`runtime/stirling/Stirling-PDF.jar`（必需）；
- `runtime/glibc`（jpdfium 原生库要求 glibc ≥ 2.35，本机 2.31；本模块自动用
  bundled loader 包一层启动，否则 merge/split 等 jpdfium 工具会失败）；
- OCR（二选一，自动降级）：
  1. 系统 `tesseract` + `runtime/stirling/tessdata`（已含 `chi_sim`、`eng`、`osd`）——优先；
  2. 没有 tesseract 时，自动改用随包的 `modules/ocr`（RapidOCR，零外部依赖），
     结果里标注 `engine:"rapidocr"`、`fallback:true`；两者都没有才返回退出码 3。
- PDF/A：系统 `gs`（Ghostscript，可选）。有 gs 就转换 PDF/A-2b；没有则返回退出码 3
  并提示安装 ghostscript（本模块不随包携带 gs）。

## 首次启动很慢（正常）

`pdf start` 第一次要生成 `settings.yml`、初始化 SQLite、JVM 预热。本机实测：

- 首次 start **77 秒**（机器繁忙时可到 90-100 秒；文件缓存热时约 22-25 秒）；
- stop 后再次 start **66 秒**（热缓存时约 20-25 秒）；
- 已在运行时再 start **0.3 秒**（直接复用）。

`run` 会自动启动并等待就绪，默认超时 **180 秒**（`start --timeout` 可调）。
超时或启动失败会终止本次进程并清理 pid/port/state，不留孤儿。

启动进度写 stderr，不要把它当成错误。端口写入 `$OFFICE_KIT_DATA/pdf/port`，
日志在 `$OFFICE_KIT_DATA/pdf/logs/console.log`（`office-kit pdf logs` 可看）。

## 常用命令（均可直接运行）

```sh
# 1) 合并（顺序按 --input 给出；支持图片输入）
office-kit pdf run merge --input 封面.pdf --input 正文.pdf --output 合并.pdf

# 2) 拆分：pageNumbers 是“切分点”，all 表示每页一个文件
office-kit pdf run split --input 报告.pdf --option pageNumbers=all --output-dir 拆分页
office-kit pdf run split --input 报告.pdf --option pageNumbers=2,5 --output-dir 三段

# 3) 旋转全部页面（90/180/270）
office-kit pdf run rotate --input 扫描.pdf --option angle=90 --output 旋转.pdf

# 4) 抽取文本层（txt；也支持 rtf）
office-kit pdf run extract-text --input 报告.pdf --output 报告.txt --json

# 5) PDF 转图片（多页返回 ZIP，自动解压到目录）
office-kit pdf run pdf-to-img --input 报告.pdf --option dpi=150 --output-dir 页面图片

# 6) 图片转 PDF（可多张，按 --input 顺序）
office-kit pdf run img-to-pdf --input 第1页.png --input 第2页.jpg --output 扫描件.pdf

# 7) 压缩（optimizeLevel 1-9，越大越激进）
office-kit pdf run compress --input 大文件.pdf --option optimizeLevel=7 --output 小文件.pdf

# 8) 加密 / 解密（密码含特殊字符时用单引号）
office-kit pdf run encrypt --input 报告.pdf --option password='S3cret-Pass' --output 加密.pdf
office-kit pdf run decrypt --input 加密.pdf --option password='S3cret-Pass' --output 解密.pdf

# 9) 水印（中文会自动选择 chinese 字形；也可只给英文）
office-kit pdf run watermark --input 报告.pdf \
  --option watermarkText='机密 CONFIDENTIAL' --option opacity=0.25 --output 水印.pdf

# 10) 扫描件 OCR（中英；结果 PDF 带可搜索文字层）
#     有 tesseract 时走 Stirling；没有时自动走内置 RapidOCR
office-kit pdf run ocr --input 扫描件.pdf \
  --option languages=chi_sim+eng --option ocrType=force-ocr --output OCR.pdf

# 11) PDF/A 归档（Stirling 端点被禁用时自动走 Ghostscript）
office-kit pdf run pdf-to-pdfa --input 报告.pdf --output 报告-PDFA.pdf

# 12) 信息 / 摘要
office-kit pdf run info --input 报告.pdf --json
office-kit pdf run summary --input 报告.pdf --json

# 13) 发现其它工具
office-kit pdf list-tools --search convert
office-kit pdf list-tools --group Security --json

# 14) 停止后端（空闲 30 分钟也会自动退出）
office-kit pdf stop
```

> 所有路径都可以包含中文和空格，命令里用引号即可。多文件输出建议 `--output-dir`；
> 单文件 ZIP 响应若给 `--output 结果.pdf` 且 ZIP 内只有一个 PDF，会自动取出该文件。

## 自助发现工具（list-tools）

工具清单**由运行中实例的 `/v1/api-docs`（OpenAPI 3）实时生成**并缓存到
`$OFFICE_KIT_DATA/pdf/tools.json`，不是手写列表。

```sh
office-kit pdf list-tools                 # 分组浏览
office-kit pdf list-tools --search ocr    # 按名称/说明搜索
office-kit pdf list-tools --json > /tmp/pdf-tools.json   # 完整字段
```

每个工具条目包含：`tool`（友好名）、`operationId`、`method`、`path`、`group`、
`summary`、`accepts`（可接受的输入类型）、`produces`、`output_kind`、
`files`（文件字段与是否多文件）、`fields`（表单字段/类型/必填/default/enum）、
`query`（查询参数）、`disabled`（是否被后端禁用）。

拿到任意端点后，直接用 `run` 调用它：

```sh
# 按 operationId、路径末段或 endpoint key 都可以
office-kit pdf run addPageNumbers --input a.pdf --option fontType=helvetica \
  --option position=5 --option fontSize=12 --output 带页码.pdf
```

`run` 会把 `--option k=v` 按 OpenAPI 类型转换后作为 multipart 表单字段发送；
数组字段可写成 `a+b` 或用多个 `--option`（如 `languages=chi_sim+eng`）。
需要上传非主文件字段时用 `--upload 字段名=文件路径`；查询参数用 `--query k=v`。

## 输出与 JSON 字段

默认（人类可读）：只把**输出文件路径**逐行打印到 stdout，进度/警告走 stderr。

`--json`：stdout 只输出一个 JSON 对象（UTF-8，不转义中文）：

```json
{
  "ok": true,
  "tool": "merge",
  "outputs": ["/path/合并.pdf"],
  "details": {
    "endpoint": "/api/v1/general/merge-pdfs",
    "operation_id": "mergePdfs",
    "http_status": 200,
    "content_type": "application/pdf",
    "bytes": 4354,
    "duration_ms": 31,
    "uploaded": [{"field": "fileInput", "filename": "封面.pdf", "bytes": 1234}],
    "fields": {"sortType": "orderProvided", "removeCertSign": "true"}
  }
}
```

- `outputs`：本次写出的文件（相对/绝对路径与传入一致）；多文件 ZIP 解压后是文件列表。
- `details.text`：文本类响应（`extract-text`）的全文。
- `details.data`：JSON 类响应（`info`/`summary`/`analysis/*`）解析后的对象。
- `details.engine`：本地兜底时标注（`pdf-to-pdfa` → `"ghostscript"`；
  OCR 内置后备 → `"rapidocr"`，同时 `details.fallback: true`）。
- `details.text` / `details.data`：OCR 内置后备时分别给出合并文本与逐页/逐行结果。
- `details.extracted`：ZIP 解压出的文件数。
- 密码类字段在 `details.fields` 中显示为 `***`。

失败时退出码非 0，stdout 仍是一个 JSON 对象（`--json` 时）：

```json
{"ok": false, "tool": "decrypt", "outputs": [],
 "error": {"http_status": 400, "message": "The PDF Document is passworded ...",
           "endpoint": "/api/v1/security/remove-password", "hint": "..."}}
```

退出码：`0` 成功；`1` 运行时/HTTP 错误；`2` 参数错误（未知工具、缺文件、缺必填参数）；
`3` 缺依赖（jar/JVM/Ghostscript 等）。stderr 会保留后端错误体的关键行与修复提示。

## 常见错误与处理

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `端口 N 已被占用` / 启动失败 | 端口被其它程序占用 | 默认会自动从 8091 递增找空闲；也可 `pdf start --port 8188`；先 `pdf stop` 清理本模块实例 |
| 启动后 `status` 显示 port null / 未就绪 | 首次启动仍在生成配置 | 等 60–100 秒；`pdf logs` 看到 `running on port: N` 即就绪；`status` 会从日志/PID 自动恢复端口 |
| `启动失败（退出码 1）` 且日志有 `BindException` | 端口竞争 | 自动换端口重试最多 5 次；仍失败用 `--port` 指定，或看 `console.log` |
| JVM 内存不足 / 处理大扫描件卡住 | 默认 `-Xmx1536m` 偏小 | `pdf stop && pdf start --force --xmx 3072m`；OCR 大文件加 `--timeout 600` |
| `Invalid OCR languages format` / 识别不出中文 | 缺 `chi_sim.traineddata` 或 tesseract 不可用 | 本模块会自动降级到内置 RapidOCR；确认 `runtime/stirling/tessdata/chi_sim.traineddata`；`languages=chi_sim+eng` |
| OCR 输出仍然是图片、没有文字 | 用了 `skip-text` 且页面已有文本层 | 扫描件用 `--option ocrType=force-ocr`；或 `OFFICE_KIT_PDF_OCR_ENGINE=rapidocr` 强制内置引擎 |
| 内置 OCR 也失败（退出码 3） | 没有 tesseract 且 `modules/ocr` 不可用 | 安装 tesseract，或确认 `modules/ocr/bin/ocr` 存在 |
| `passworded ... incorrect` | PDF 有密码或密码错 | 先 `pdf run decrypt --option password=...`；不知道密码则无法处理 |
| 水印报 `No glyph for U+xxxx` | 中文字体缺失 | 本模块会自动设 `alphabet=chinese`；若仍失败改用英文水印或 `--option alphabet=chinese` |
| `端点 xxx 被 Stirling 禁用` | 缺 LibreOffice/qpdf 等外部程序 | PDF/A 会自动用 Ghostscript 兜底；其它工具需安装对应程序后 `pdf stop && pdf start`，再 `pdf list-tools --refresh` 更新缓存 |
| `pdf-to-pdfa` 报缺 Ghostscript（退出码 3） | 系统没有 `gs` | 安装 ghostscript，或设置 `OFFICE_KIT_GS=/path/to/gs`；也可先用 `office-kit office convert` 生成普通 PDF（非 PDF/A） |
| 返回 ZIP 但只给了一个 `.pdf` 输出 | 端点是 SIMO（一进多出） | 用 `--output-dir 目录` 或 `--output 结果.zip` |
| 中文/空格路径出错 | 未加引号或用了 `eval` | 始终用双引号包住路径；本模块内部全部按字符串处理，不做 shell 展开 |
| 后端未运行但想快速看工具列表 | 冷启动慢 | `pdf list-tools` 会优先读真实 OpenAPI 生成的缓存（`from_cache:true`）；`--refresh` 强制刷新 |

## 资源与数据目录

- 运行数据：`$OFFICE_KIT_DATA/pdf/`（`configs/`、`logs/`、`work/`、`port`、`pid`、`state.json`、`tools.json`）。
- 临时文件：`$OFFICE_KIT_CACHE/pdf/`（JVM `java.io.tmpdir` 也指向 `cache/pdf/tmp`）；测试临时文件：仓库 `.tmp/pdf-test/`。
- 空闲退出：默认 30 分钟无 `run` 自动停止（watchdog 进程）；`pdf start --idle-timeout 0` 关闭。
- 输出只写到用户指定的 `--output`/`--output-dir` 与上述数据/缓存目录。

## 离线边界

- 后端只监听 `127.0.0.1`，不访问互联网；`pdf` 不发任何遥测/更新请求。
- 所有处理在本机 JVM / tesseract / RapidOCR / Ghostscript 内完成；不调用云 API、不下载模型。
- `office-kit pdf list-tools` 读取的是本机 OpenAPI 文档，不联网。
- 若在完全断网环境运行，请避免给 `start` 之外的命令设置代理；本模块的 HTTP 客户端直连
  `127.0.0.1`，不会使用 `http_proxy`。

## 内存与常驻（低配机器必读）

Stirling 后端是**唯一常驻**的进程：空闲约 600–800 MB，默认空闲 **10 分钟**自动退出。

```sh
office-kit pdf status          # 看是否在跑、端口、pid
office-kit pdf stop            # 立即释放
office-kit pdf start --low-memory   # Xmx=768m + 空闲 5 分钟 + SerialGC
export OFFICE_KIT_PDF_ONESHOT=1     # 每次 run 结束就停后端（省内存，但每次多等启动）
```

- 别的技能（office/ofd/ocr/asr）都是用完即退，不会常驻。
- 内存峰值：office 转换约 1.5 GB、OCR 约 800 MB、ASR 约 270 MB、OFD 约 150 MB，
  建议避免多个重任务并行。
- 后端首次启动 20–90 秒，之后复用约 0.3 秒；如果只是偶尔处理一次 PDF，
  用 `OFFICE_KIT_PDF_ONESHOT=1` 更划算。

## 命令入口（离线机必读）

本技能假设 `office-kit` 已在 `PATH` 中。若执行时报 `command not found`，改用 AppImage 绝对路径：

```sh
KIT="${OFFICE_KIT_BIN:-$HOME/apps/office-kit.AppImage}"
"$KIT" --version
```

后文所有 `office-kit <分组> ...` 都可以等价替换为 `"$KIT" <分组> ...`。
AppImage 需要 `chmod +x`；若提示 FUSE 不可用，加环境变量 `APPIMAGE_EXTRACT_AND_RUN=1`。
