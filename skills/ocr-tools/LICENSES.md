# ocr-tools 第三方组件与许可

本技能通过 `office-kit ocr`（`modules/ocr/`）实现离线 OCR。下列组件由**共享运行时**
`runtime/python` 提供，本仓库不再单独打包副本。版本以 `office-kit ocr list-langs` / README 记录为准
（当前环境：aarch64 / Kylin V10 / glibc 2.31）。

## 运行期依赖

| 组件 | 版本 | 许可证 | 来源 | 用途 |
| --- | --- | --- | --- | --- |
| RapidOCR（rapidocr_onnxruntime） | 1.4.4 | Apache-2.0 | PyPI `rapidocr_onnxruntime`（RapidAI/RapidOCR） | OCR 引擎调度、检测/识别/方向分类 |
| PP-OCRv4 模型（det / rec / cls） | v4 | Apache-2.0 | 随 `rapidocr_onnxruntime` wheel 内置（源自 PaddleOCR） | 中文+英文文字检测与识别；字表写在 ONNX metadata |
| ONNX Runtime | 1.32.0 | MIT | PyPI `onnxruntime` | CPU 推理 |
| NumPy | 2.5.5 | BSD-3-Clause | PyPI `numpy` | 数组运算 |
| OpenCV（opencv-python-headless） | 5.1.0.95 | Apache-2.0 | PyPI `opencv-python-headless` | 图像预处理、透视裁切 |
| Pillow | 13.0.0 | HPND（PIL Software License） | PyPI `pillow` | 图片解码/编码、缩放 |
| PyMuPDF | 2.1 | **AGPL-3.0**（亦提供商业许可） | PyPI `pymupdf` | PDF 逐页渲染；测试数据生成 |

## 可选组件（目标机不一定存在）

| 组件 | 版本 | 许可证 | 来源 | 用途 |
| --- | --- | --- | --- | --- |
| tesseract | 系统版本（当前 4.1.1） | Apache-2.0 | 系统包 / 构建期安装 | 可选后备 OCR 引擎、OSD 方向检测 |
| tessdata：`chi_sim` / `eng` / `osd` | 4.x | Apache-2.0 | 系统 tessdata 或 `runtime/stirling/tessdata/` | 中文/英文识别与方向检测 |

## 参考实现

| 项目 | 许可证 | 使用方式 |
| --- | --- | --- |
| [Umi-OCR](https://github.com/hiroi-sora/Umi-OCR)（`UmiOCR-data/py_src/ocr/`） | MIT | 参考其离线引擎选择、文块（text block）结构与版面后处理思路；**未复制 Qt 界面代码**，也未引入其二进制 |

## 许可证注意事项

1. **PyMuPDF 为 AGPL-3.0**：本模块用它做 PDF 渲染与测试数据生成。若整个 office-kit 以闭源
   方式分发，需要替换为 Apache/BSD 许可的渲染方案，或取得 Artifex 商业许可。请在打包/分发前
   与主项目确认。RapidOCR/ONNX Runtime/NumPy/OpenCV/Pillow 均为宽松许可（Apache-2.0 / MIT /
   BSD / HPND），保留版权与许可声明即可。
2. **Apache-2.0 组件**（RapidOCR、OpenCV、tesseract）：再分发时需保留 `LICENSE`/`NOTICE`
   与版权声明。RapidOCR 的模型权重来自 PaddleOCR（Apache-2.0），随 wheel 分发时应一并保留
   其许可信息。
3. **tesseract 与 tessdata** 仅在系统已安装时被调用，本仓库不打包其二进制；`runtime/stirling/`
   下的 tessdata 由主智能体随 Stirling-PDF 部署（Apache-2.0）。
4. 若在 `modules/ocr/lib/models/` 固化 ONNX 模型作为兜底，该目录内容同样来自 PaddleOCR /
   RapidOCR（Apache-2.0），需保留许可说明。

## 上游链接

- RapidOCR：<https://github.com/RapidAI/RapidOCR>
- PaddleOCR（模型来源）：<https://github.com/PaddlePaddle/PaddleOCR>
- ONNX Runtime：<https://github.com/microsoft/onnxruntime>
- OpenCV：<https://github.com/opencv/opencv>
- Pillow：<https://github.com/python-pillow/Pillow>
- PyMuPDF：<https://github.com/pymupdf/PyMuPDF>
- tesseract：<https://github.com/tesseract-ocr/tesseract>
- Umi-OCR：<https://github.com/hiroi-sora/Umi-OCR>
