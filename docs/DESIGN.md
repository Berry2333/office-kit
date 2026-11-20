# 技术选型与验证记录

本文件记录 office-kit 每个能力最终采用的引擎、为什么选它、以及在本机（Kylin V10
aarch64 / glibc 2.31）上的实测证据。所有引擎都已验证**离线可运行**。

## 总览

| 能力 | 引擎 | 形态 | 体积（约） | 离线 | 验证 |
| --- | --- | --- | --- | --- | --- |
| Office 转换/渲染/重算 | LibreOffice 25.x（dsh-libreoffice-kit WASM） | `soffice.wasm` + Node 22 | 146 MB + 60 MB | ✅ | `convert` docx→pdf 成功，`capabilities` 正常 |
| Office 创建/编辑 | python-docx / openpyxl / python-pptx | CPython 3.12 | 少量 | ✅ | 生成 docx/xlsx/pptx 并回读 |
| PDF 处理 | Stirling-PDF 3.1.0 | Spring Boot jar + JRE 25 | 251 MB + 64 MB | ✅ | headless 启动 + REST `/api/v1/info/status` UP |
| OFD | ofdrw 2.5.1 | Java CLI | jar 依赖约 20 MB | ✅ | 生成 OFD → 转 PDF/图片/文本 |
| OCR | RapidOCR 1.4.4（PP-OCRv4 ONNX） | CPython + onnxruntime | 约 100 MB（含模型） | ✅ | 模型随 wheel 内置，断网识别 |
| ASR | SenseVoiceSmall Q8（llama-funasr） | 原生 aarch64 可执行 | 243 MB 模型 + 3.7 MB | ✅ | 英文语音 2.5s 出结果 |
| 录音/转码 | ffmpeg / arecord | 系统或内置 | - | ✅ | 16k 单声道归一化 |

## 为什么这样组合

### Office：LibreOffice WASM 而不是系统 LibreOffice

目标机不装 LibreOffice，且完整 LibreOffice 安装约 500 MB+ 且依赖大量系统库。
DSH 已内置 `@deepseek-ai/libreoffice-kit` 的 **WASM 后端**：同一套 LibreOffice
排版引擎，编译为 WebAssembly，由 Node 22 加载，不依赖 X11、字体配置或系统 soffice。

- 优点：体积可控、启动快（约 1–2 s/次）、跨机器行为一致、无 GUI 依赖。
- 限制：字体需随包提供；`missingFonts` 会在 JSON 中透传；二进制 `.doc/.xls/.ppt`
  支持但版式可能与 MS Office 有差异。
- 备选：完整 `soffice --headless`（未采用，体积与依赖不可控）。

### PDF：直接复用 Stirling-PDF 后端

用户已有 Stirling-PDF 桌面版构建（Electron + Spring Boot）。桌面壳对 DSH 无用，
因此只打包 **后端 jar + JRE + jpdfium + tessdata**，由 `pdf` 模块以 headless 方式
拉起本地端口，通过官方 REST API 调用 50+ 工具。Electron 壳（约 210 MB）不打包。

- 冷启动 20–40 s，常驻复用；`pdf status` / `pdf stop` 管理生命周期。
- 数据目录隔离在 `~/.local/share/office-kit/pdf`，端口自动探测（8091+）。
- 加密/水印/压缩/OCR（tesseract `chi_sim`）全部走官方端点，不重复造轮子。

### OFD：ofdrw + 独立 Java CLI

OFD 是国产版式文档（GB/T 33190），Python 生态几乎没有可靠实现。ofdrw 是
Apache-2.0 的 Java 参考实现，提供 reader/layout/converter。AppImage 内置
jlink 精简 JRE 25（含 `java.desktop` 供字体度量），所以目标机无需装 Java。

### OCR：RapidOCR 而不是打包 Umi-OCR

Umi-OCR 是 Windows + PySide2 桌面应用，Linux/ARM 不可直接复用；其识别核心是
PP-OCRv4（ONNX）。因此直接采用 `rapidocr_onnxruntime`：

- 模型（det/cls/rec）随 wheel 内置，**不联网**；
- 中文/英文混排开箱即用；输出按行的框坐标，便于模型做版面分析；
- tesseract 作为可选后备（目标机若有），并用 AppImage 内置 `tessdata`。

### ASR：复用 asr-now 的 Lite 引擎

asr-now 的 Lite 版把 SenseVoiceSmall 转成 GGUF，用 `llama-funasr-sensevoice`
（llama.cpp 后端）推理，单条命令即可转写，无需 Python 依赖、无需 sherpa。

- 模型 `sensevoice-small-q8.gguf`（243 MB）随包；16 kHz 单声道 WAV；
- 自带标点与 ITN，中文效果好；
- 未打包 285 MB 的 CT-Transformer 标点模型（体积/收益不划算）。

## 实测命令（构建机）

```sh
# LibreOffice WASM
runtime/node/bin/node runtime/node/lib/node_modules/@deepseek-ai/libreoffice-kit/lib/cli.js \
  convert --input test.docx --output test.pdf
# {"backend":"wasm","missingFonts":["Arial"],"outputPath":"test.pdf"}

# Stirling
runtime/jre/bin/java -Dserver.port=8099 -jar runtime/stirling/Stirling-PDF.jar
curl -s localhost:8099/api/v1/info/status   # {"version":"3.1.0","status":"UP"}

# SenseVoice
runtime/models/llama/llama-funasr-sensevoice \
  -m runtime/models/sensevoice/sensevoice-small-q8.gguf -a speech.wav
# Hello, roll, this is an offline speech recognition test.
```

## 已知限制

1. LibreOffice WASM 单次转换内存约 300–600 MB，超大文档需 `--timeout-ms`。
2. 中文字体依赖宿主字体目录；缺失时 PDF 可能回退字形，`missingFonts` 会提示。
3. Stirling 首次 OCR 需要 `tessdata`（已内置 chi_sim/eng/osd）。
4. SenseVoice 对长音频按整段处理；超长会议建议用 `asr listen` 分句或先切片。
5. 所有能力仅 aarch64；x86_64 需要重新构建对应引擎产物。
