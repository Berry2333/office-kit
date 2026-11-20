# 第三方组件与许可

office-kit 打包/聚合了以下上游组件。各组件版权归其作者所有，许可文本随 AppImage
内 `licenses/` 与各技能 `LICENSES.md` 分发。

| 组件 | 版本 | 许可证 | 用途 | 位置 |
| --- | --- | --- | --- | --- |
| LibreOffice（经 `@deepseek-ai/libreoffice-kit` WASM 构建） | 25.x | MPL-2.0 | Office → PDF / 渲染 / 重算 | `runtime/node/lib/node_modules/@deepseek-ai/libreoffice-kit*` |
| Node.js | 22.23.3 | MIT | 运行 LibreOffice Kit | `runtime/node/bin/node` |
| Stirling-PDF | 3.1.0 | MIT | PDF 工具后端 | `runtime/stirling/Stirling-PDF.jar` |
| PDFium（jpdfium） | 随 Stirling | BSD-3-Clause | PDF 渲染/合并 | `runtime/stirling/native/` |
| Eclipse Temurin JDK（jlink 运行时） | 25.0.4.1 | GPLv2 + Classpath Exception | 运行 Stirling / ofdrw | `runtime/jre/` |
| ofdrw | 2.5.1 | Apache-2.0 | OFD 读写/转换 | `modules/ofd/lib/jars/` |
| Apache PDFBox / FontBox | 3.0.8 | Apache-2.0 | OFD→PDF | `modules/ofd/lib/jars/` |
| Apache Batik / XML Graphics | 1.19 / 2.11 | Apache-2.0 | OFD→SVG/HTML | `modules/ofd/lib/jars/` |
| Bouncy Castle | 1.85 | MIT | OFD 签名/加密 | `modules/ofd/lib/jars/` |
| CPython | 3.12.15 | PSF-2.0 | 办公/OCR 运行时 | `runtime/python/` |
| python-docx | 1.2.0 | MIT | DOCX 生成/读取 | `runtime/python/.../site-packages` |
| openpyxl | 3.1.5 | MIT | XLSX 生成/读取 | 同上 |
| xlwt | 1.3.0 | BSD-3-Clause | 测试中生成 .xls/.et 素材 | 同上 |
| python-pptx | 1.0.2 | MIT | PPTX 生成/读取 | 同上 |
| lxml | 6.1.3 | BSD-3-Clause | OOXML 解析 | 同上 |
| PyMuPDF | 2.1 | **AGPL-3.0** | PDF 页渲染 / 文本 | 同上 |
| Pillow | 13.0.0 | MIT-CMU | 图像处理 | 同上 |
| NumPy | 2.5.5 | BSD-3-Clause | 数值计算 | 同上 |
| ONNX Runtime | 1.32.0 | MIT | OCR 推理 | 同上 |
| OpenCV（headless） | 5.1.0 | Apache-2.0 | OCR 图像处理 | 同上 |
| RapidOCR | 1.4.4 | Apache-2.0 | 文字识别 | 同上 |
| PP-OCRv4 模型（det/rec/cls） | 2024 | Apache-2.0 | OCR 模型权重 | `runtime/python/.../rapidocr_onnxruntime/models/` |
| SenseVoiceSmall（GGUF Q8） | 2026 | MIT / FunASR Model License 1.1 | 语音识别模型 | `runtime/models/sensevoice/` |
| llama-funasr-sensevoice（llama.cpp 派生） | 2026 | MIT | 语音推理二进制 | `runtime/models/llama/` |
| Tesseract OCR | 系统可选 | Apache-2.0 | PDF OCR / ODF 后备引擎 | 系统路径；`tessdata` 在 `runtime/stirling/tessdata` |
| Ghostscript | 系统可选 | AGPL-3.0 | PDF/A 转换兜底 | 系统路径 |
| ffmpeg | 系统可选 | LGPL/GPL | 音频转码、录音 | 系统路径 |

## 需要特别注意的许可

1. **PyMuPDF（AGPL-3.0）**：用于 PDF 页面渲染与文本提取（OCR 模块、PDF 模块辅助）。
   若将 office-kit 作为闭源商业产品分发，需替换为 PDFium/poppler 等宽松许可方案，
   或取得 Artifex 商业许可。个人/内部使用不受影响。
2. **Ghostscript（AGPL-3.0）**：仅作为可选系统依赖，未打包；只影响 PDF/A 转换。
3. **LibreOffice（MPL-2.0）**：以独立 WASM 资产形式分发，未修改源码；MPL 要求对
   LibreOffice 源文件的修改（若有）保持 MPL 许可。
4. **SenseVoice 模型**：FunASR Model License 1.1，允许研究与商业使用，再分发需保留
   模型名称与许可声明（见 `skills/asr-voice/LICENSES.md`）。
5. **Temurin JDK（GPLv2+CE）**：以未修改的 jlink 运行时形式随包，Classpath
   Exception 允许与其它代码链接。

## 系统依赖（可选，不打包）

| 程序 | 影响的降级行为 |
| --- | --- |
| `tesseract` | Stirling OCR 优先使用；缺失时 `pdf run ocr` 回退到内置 RapidOCR |
| `ghostscript` (`gs`) | `pdf run pdf-to-pdfa` 需要；缺失时退出码 3 并提示 |
| `ffmpeg` | 语音任意格式转码；缺失时仅支持 PCM WAV |
| `arecord` | 麦克风录音；缺失时尝试 ffmpeg ALSA |
| `xclip`/`wl-copy`/`ydotool` | `asr input` 剪贴板与自动粘贴；缺失时打印文本 |
