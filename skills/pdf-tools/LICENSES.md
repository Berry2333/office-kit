# 第三方组件与许可证（pdf-tools）

本仓库自写代码遵循 office-kit 的许可；运行时与随包 jar 内含下列上游组件（不完全列举）。
版本为本仓库实际使用的版本，许可证以各上游仓库/jar 内声明为准。目标机离线分发时，
请连同各自许可证文本一起提供。

## 核心后端

| 组件 | 版本 | 许可证 | 用途 / 来源 |
| --- | --- | --- | --- |
| Stirling-PDF | 3.1.0 | MIT（Open-Core） | headless PDF 后端；`runtime/stirling/Stirling-PDF.jar`。上游标注 “Open-Core - MIT Licensed”，见 <https://github.com/Stirling-Tools/Stirling-PDF> |
| Spring Boot / Spring Framework | 4.1.1 | Apache-2.0 | Stirling 的 Web 容器与依赖注入 |
| Eclipse Jetty | 12.1.12 | EPL-2.0 或 Apache-2.0（双许可） | HTTP 服务器 |
| Apache PDFBox / FontBox / XMPBox | 3.0.8 | Apache-2.0 | PDF 解析、文本抽取、加密、表单等 |
| Apache PDFBox Preflight | 3.0.8 | Apache-2.0 | PDF/A 校验/转换（Stirling 内部） |
| veraPDF（validation-model / metadata-fixer / xmp-core 等） | 1.30.2 | GPL-3.0+ / MPL-2.0（双许可，见上游） | PDF/A、PDF/UA 校验；随 Stirling jar 分发 |
| Apache POI | 5.5.1 | Apache-2.0 | Office 相关端点 |
| jpdfium | 1.1.5 | 随 Stirling-PDF 分发；见上游 Stirling-Tools/JPDFium | 合并/拆分/重排等 PDFium 绑定。**fat jar 仅内置 linux-x64 原生库**，aarch64 原生库由 `runtime/stirling/native/` 提供 |
| PDFium | 随 jpdfium natives | BSD-3-Clause（Chromium 项目） | PDF 渲染引擎 |
| Ghostscript | 9.50（系统可选） | AGPL-3.0（Artifex） | **PDF/A 兜底**；不随包分发。见 <https://www.ghostscript.com/licensing/> |
| Tesseract OCR | 4.1.1（系统可选） | Apache-2.0 | 扫描件 OCR；不随包分发 |
| tessdata（chi_sim / eng / osd） | Tesseract 5 格式 | Apache-2.0 | 语言模型；位于 `runtime/stirling/tessdata/`，见 <https://github.com/tesseract-ocr/tessdata> |

## 内置 OCR 兜底（modules/ocr）

| 组件 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| RapidOCR / rapidocr_onnxruntime | 随 `modules/ocr` | Apache-2.0 | 无 tesseract 时的 PDF/图片文字识别 |
| ONNX Runtime | 随 `modules/ocr` | MIT | RapidOCR 推理后端 |
| OpenCV（headless） | 随 `modules/ocr` | Apache-2.0 | 图像预处理 |
| NumPy | 随 `modules/ocr` | BSD-3-Clause | 数值计算 |

## 本模块直接使用的 Python 库

| 组件 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| Python | 3.12.15 | PSF-2.0 | `runtime/python` |
| PyMuPDF（fitz） | 2.1（MuPDF 1.28.6） | **AGPL-3.0**（或 Artifex 商业许可） | `test.sh` 生成/校验 PDF；**OCR 兜底时生成不可见文字层**。见 <https://pymupdf.readthedocs.io/en/latest/about.html#license> |
| Pillow | 13.0.0 | HPND（Pillow License） | 随 runtime 提供，本模块未直接使用 |

> **AGPL 注意**：PyMuPDF 采用 AGPL-3.0。若以二进制形式分发包含 PyMuPDF 的
> office-kit，需要遵守 AGPL 的源码提供义务，或向 Artifex 购买商业许可。
> 本模块只在“无 tesseract 的 OCR 兜底”和自检脚本中使用它；`test.sh` 可改为不依赖 PyMuPDF，
> 但 OCR 兜底生成可搜索 PDF 需要它（或改用 PDFBox/jpdfium 渲染）。

## 本模块自带数据

| 文件 | 来源 | 许可/说明 |
| --- | --- | --- |
| `modules/pdf/lib/icc/sRGB.icc` | Ghostscript 色彩配置（Ubuntu `ghostscript` 包的 `/usr/share/color/icc/ghostscript/srgb.icc`） | ICC 色彩配置文件数据；随 Ghostscript 发行版分发。仅用于 PDF/A 输出意图 |

## 未随包分发的系统程序

以下程序**不在仓库内**，缺失时对应功能降级或退出码 3：

- **Ghostscript（gs）**：仅 PDF/A 兜底使用；系统有则用，无则提示安装。AGPL-3.0。
- **Tesseract（tesseract）**：Stirling OCR 使用；系统有则优先，无则自动改用随包 RapidOCR。
  Apache-2.0。
- **LibreOffice（soffice）/ qpdf / ImageMagick / Calibre**：Stirling 的可选外部依赖，
  缺失时会禁用 PDF→Word/HTML/PPT、repair、部分 compress 等端点。各自许可证见上游
  （LibreOffice MPL-2.0、qpdf Apache-2.0、ImageMagick ImageMagick License、Calibre GPL-3.0）。

## 参考资料

- Stirling-PDF 许可证：<https://github.com/Stirling-Tools/Stirling-PDF/blob/main/LICENSE>
- Stirling 技术栈/开源组件：<https://docs.stirlingpdf.com/Developers/Technologies/>
- Apache PDFBox：<https://pdfbox.apache.org/>
- veraPDF：<https://verapdf.org/>
- Tesseract：<https://github.com/tesseract-ocr/tesseract>
- RapidOCR：<https://github.com/RapidAI/RapidOCR>
- PyMuPDF 许可：<https://pymupdf.readthedocs.io/en/latest/about.html#license>
- Ghostscript 许可：<https://www.ghostscript.com/licensing/>
