# office-kit · 离线办公文档工具箱（DSH 技能套件）

把 **Word / Excel / PowerPoint、PDF、OFD、OCR、语音识别** 五类能力，做成
**完全离线**、可安装进 DeepSeek Harness（DSH）的 5 个技能 + 1 个自包含 AppImage。

> 目标形态：`SKILL.md × 5` + `office-kit-*.AppImage`。
> 目标机 aarch64（Kylin V10 / UOS ARM），不预装 Java / Node / Python / LibreOffice，
> 不联网，拷贝即用。

## 五个技能

| 技能 | 目录 | 能力 | 引擎 |
| --- | --- | --- | --- |
| `office-docs` | `skills/office-docs` | DOCX/XLSX/PPTX + WPS（.wps/.et/.dps）创建、转换、逐页渲染、公式重算 | LibreOffice Kit（WASM 后端）+ python-docx/openpyxl/python-pptx |
| `pdf-tools` | `skills/pdf-tools` | 合并/拆分/旋转/加密/解密/水印/压缩/抽文本/转图片/OCR/PDF-A | Stirling-PDF 3.1.0（headless + REST API） |
| `ofd-tools` | `skills/ofd-tools` | OFD 解析、转 PDF/图片/文本/HTML、合并 | ofdrw 2.5.1（Java） |
| `ocr-tools` | `skills/ocr-tools` | 图片/扫描件/PDF 文字识别，带坐标 JSON | RapidOCR（PP-OCRv4 ONNX）+ 可选 tesseract |
| `asr-voice` | `skills/asr-voice` | 语音转写、SRT 字幕、麦克风听写、语音输入 | SenseVoiceSmall（llama.cpp/funasr）+ ffmpeg |

统一入口：

```sh
office-kit <group> <subcommand> [...]
office-kit --help
```

## 快速开始

```sh
# 1. 构建 AppImage（构建机需联网下载/组装一次；产物完全离线）
bash build/build-appimage.sh

# 2. 安装到本机并注册 DSH 技能
./install.sh

# 3. 自检
office-kit --version
office-kit list
office-kit pdf --help

# 4. 端到端验收（可选，约 3 分钟）
bash test/integration.sh
# 或验证 AppImage 本身：
KIT_APPIMAGE=dist/office-kit-1.0.0-linux-arm64.AppImage bash test/integration.sh
```

产物：`dist/office-kit-1.0.0-linux-arm64.AppImage`（约 **812 MB**，zstd 压缩，内置
JRE/Node/Python/Stirling/OFD 依赖/OCR 模型/SenseVoice 模型）+ `.sha256`。

离线拷贝到目标机：

```sh
# 目标机（aarch64）
mkdir -p ~/apps
cp office-kit-1.0.0-linux-arm64.AppImage ~/apps/office-kit.AppImage
chmod +x ~/apps/office-kit.AppImage
~/apps/office-kit.AppImage --help

# 技能目录（把 5 个目录复制到 DSH 技能根）
cp -r skills/* ~/.dsh/skills/
```

## 常用示例

```sh
# Office：Word 转 PDF、渲染首页、Excel 重算
office-kit office convert --input 年度报告.docx --output 年度报告.pdf
office-kit office convert --input 附件册.wps --output 附件册.pdf      # WPS 文档
office-kit office info    --input 预算.et --json                     # WPS 表格
office-kit office render  --input 汇报.pptx --output-dir preview --pages 1-3 --dpi 144
office-kit office recalc  --input 预算.xlsx --output 预算-重算.xlsx

# PDF：合并 + 加水印 + 抽文本
office-kit pdf run merge --input a.pdf --input b.pdf --output ab.pdf
office-kit pdf run watermark --input ab.pdf --output ab-wm.pdf --option watermarkText=内部资料
office-kit pdf run extract-text --input ab.pdf --output ab.txt

# OFD：发票转 PDF / 文本
office-kit ofd to-pdf  --input 发票.ofd --output 发票.pdf
office-kit ofd info    --input 发票.ofd --json

# OCR：扫描件识别（带坐标）
office-kit ocr pdf --input 扫描件.pdf --pages 1-3 --json > ocr.json

# 语音：录音转文字 / 生成字幕 / 麦克风听写
office-kit asr file --input 会议.m4a --format srt
office-kit asr mic  --seconds 10
office-kit asr listen
```

## 架构

```
office-kit.AppImage
└── usr/share/office-kit
    ├── bin/office-kit          统一 CLI（定位根目录、导出环境变量、分发子命令）
    ├── modules/{office,pdf,ofd,ocr,asr}/   各模块入口 + 私有依赖
    ├── runtime/
    │   ├── jre/                Temurin 25 jlink（ofdrw 用）
    │   ├── node/               Node 22 + LibreOffice Kit（WASM 引擎）
    │   ├── python/             CPython 3.12 + 办公/OCR 库
    │   ├── stirling/           Stirling-PDF.jar + jpdfium + tessdata
    │   └── models/             SenseVoiceSmall Q8 + llama-funasr 可执行
    └── skills/                 5 个 SKILL.md（安装时复制到 ~/.dsh/skills）
```

详见 [docs/DESIGN.md](docs/DESIGN.md)（技术选型与验证记录）和
[docs/OFFLINE-DEPLOY.md](docs/OFFLINE-DEPLOY.md)（离线部署 / 内网分发）。

## 离线边界

- **运行期零网络**：所有模型、依赖、字体、语言包随 AppImage 分发；模块不会下载任何东西。
- **构建期需要网络**（仅一次）：npm 包、PyPI wheel、Maven jar、JDK；产物落地后即可断网。
- 首次调用 Stirling 后端需 20–40 秒冷启动，之后常驻复用；`office-kit pdf stop` 可释放内存。

## 质量门禁

每个模块都有断网自检，全部通过才发布：

```sh
bash modules/office/test.sh   # OK office
bash modules/pdf/test.sh      # OK pdf
bash modules/ofd/test.sh      # OK ofd
bash modules/ocr/test.sh      # OK ocr
bash modules/asr/test.sh      # OK asr
bash test/integration.sh      # 37 项跨模块验收 → PASS
```

`build/release.sh` 会串起：5 个模块自检 → 清理 → 打包 → AppImage 冒烟 → 发布说明。

## 资源占用与常驻说明

**只有 PDF 后端会常驻**，其余四个能力都是「用完即退」的一次性进程。

| 能力 | 内存峰值 | 是否常驻 | 说明 |
| --- | --- | --- | --- |
| `asr-voice` | 约 270 MB | 否 | 每次加载模型，转写完即释放 |
| `ofd-tools` | 约 150 MB | 否 | 每次起一个 JVM，退出即释放 |
| `ocr-tools` | 约 800 MB | 否 | onnxruntime + 图像处理，批量时只加载一次模型 |
| `office-docs` | 约 1.5 GB | 否 | LibreOffice WASM 引擎瞬时占用，转换结束即回收 |
| `pdf-tools` | 空闲约 600–800 MB | **是**（默认空闲 10 分钟退出） | Stirling JVM；`run` 复用，不再重复启动 |

### 低配机器的建议

```sh
# 1) 低内存预设：Xmx=768m、空闲 5 分钟退出、SerialGC
office-kit pdf start --low-memory

# 2) 更彻底：每次 PDF 操作后立即退出后端（代价是每次多等 20-90 秒启动）
export OFFICE_KIT_PDF_ONESHOT=1

# 3) 手动释放
office-kit pdf stop

# 4) 调整空闲时间（0 = 不自动退出）
office-kit pdf start --idle-timeout 300
```

- 不要同时跑 `office convert` 和 `ocr`（两者峰值叠加约 2.3 GB）。
- 只需要预览版面时用 `render`（比转 PDF 后再看更省内存）；不需要 PDF/A、OCR 时避免 `--low-memory` 之外的额外并发。
- PDF 后端内存主要花在 Spring 容器和 PDFium 上，`--xmx` 调小对空闲占用影响有限，真正有效的是「用完就 stop」。

> AppImage 模式首次 `pdf start` 会把 PDF 引擎解包到数据目录（约 390 MB，只一次），
> 这是磁盘占用，不是内存。

## 环境要求

| 项 | 要求 |
| --- | --- |
| 架构 | aarch64（ARM64） |
| 系统 | Kylin V10 SP1 / UOS ARM，glibc ≥ 2.31 |
| 内存 | 建议 ≥ 8 GB（Stirling 后端 -Xmx1536m，OCR/ASR 峰值约 1–2 GB） |
| 磁盘 | AppImage 约 812 MB；AppImage 模式首次用 PDF 会再解包约 390 MB 到数据目录 |
| FUSE | `libfuse2`（缺失时可用 `--appimage-extract-and-run`） |

## 许可证

各上游组件许可见 `skills/*/LICENSES.md` 与 AppImage 内 `licenses/`：
LibreOffice（MPL-2.0）、Stirling-PDF（MIT）、ofdrw（Apache-2.0）、
SenseVoice / FunASR（MIT/Apache-2.0）、RapidOCR（Apache-2.0）、
Tesseract（Apache-2.0）、CPython（PSF）、Node.js（MIT）、Temurin JDK（GPLv2+CE）。
