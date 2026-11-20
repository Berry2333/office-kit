# office-kit 工程契约（所有子智能体必读）

本仓库把 5 个离线办公能力做成 DSH 技能：`office-docs` / `pdf-tools` / `ofd-tools` /
`ocr-tools` / `asr-voice`。所有能力共用一个自包含运行时与一个 CLI：`office-kit`。

## 0. 环境事实

- 主机：aarch64（Kylin V10 / glibc 2.31），**离线目标机不联网**；构建阶段允许联网下载依赖。
- 工作目录：`/home/link/桌面/office`（仓库根，下称 `$KIT`）。
- 目标机不预装 Java / Node / Python / LibreOffice，全部由 `runtime/` 提供。
- 只用 aarch64 二进制；不要引入 x86_64 产物。
- 不要修改 `runtime/` 里已就位的共享资产（除非你的模块明确需要追加文件，追加到自己的
  `modules/<group>/lib/`）。

## 1. 目录布局

```
$KIT/
  runtime/                 # 我（主智能体）已就位的共享运行时，勿动
    jre/                   # Temurin 25 jlink JRE（bin/java，含 java.desktop/java.xml/java.sql）
    node/                  # Node 22 + node_modules(@deepseek-ai/libreoffice-kit[+wasm])
    python/                # CPython 3.12（bin/python3）
    stirling/              # Stirling-PDF.jar + native/ + tessdata/
    models/sensevoice/     # sensevoice-small-q8.gguf
    models/llama/          # llama-funasr-sensevoice
  modules/<group>/         # 每个模块自己的代码
    bin/<group>            # 可执行入口（bash 或 python，必须 chmod +x）
    lib/                   # 模块私有依赖（jar、wheel、数据）
    test.sh                # 自检脚本：成功退出码 0，打印 OK
    README.md              # 模块实现说明
  skills/<skill>/          # 用户可安装的技能包
    SKILL.md               # YAML frontmatter(name, description) + 正文
    scripts/               # 可选辅助脚本
    LICENSES.md            # 第三方许可与来源
  build/build-appimage.sh  # 由主智能体负责
```

## 2. CLI 契约

用户/模型统一调用：

```sh
office-kit <group> <subcommand> [flags]
```

`bin/office-kit` 负责：解析根目录、导出环境变量、把 `"$@"` 原样传给
`modules/<group>/bin/<group>`。因此模块入口必须自己处理 `--help`。

### 2.1 模块可依赖的环境变量（由 office-kit 导出）

| 变量 | 含义 |
| --- | --- |
| `OFFICE_KIT_ROOT` | 仓库/AppDir 内容根目录（含 `runtime/`、`modules/`） |
| `OFFICE_KIT_RUNTIME` | `$OFFICE_KIT_ROOT/runtime` |
| `OFFICE_KIT_DATA` | 可写数据目录，默认 `${XDG_DATA_HOME:-$HOME/.local/share}/office-kit` |
| `OFFICE_KIT_CACHE` | `$OFFICE_KIT_DATA/cache` |
| `OFFICE_KIT_LOGS` | `$OFFICE_KIT_DATA/logs` |
| `OFFICE_KIT_PY` | `$OFFICE_KIT_RUNTIME/python/bin/python3` |
| `OFFICE_KIT_PY_SITE` | `$OFFICE_KIT_RUNTIME/python/lib/python3.12/site-packages` |
| `OFFICE_KIT_JAVA` | `$OFFICE_KIT_RUNTIME/jre/bin/java` |
| `OFFICE_KIT_NODE` | `$OFFICE_KIT_RUNTIME/node/bin/node` |
| `OFFICE_KIT_NODE_MODULES` | `$OFFICE_KIT_RUNTIME/node/lib/node_modules` |
| `OFFICE_KIT_STIRLING` | `$OFFICE_KIT_RUNTIME/stirling` |
| `OFFICE_KIT_MODELS` | `$OFFICE_KIT_RUNTIME/models` |
| `OFFICE_KIT_LANG` | `zh_CN`（默认） |

模块内取路径时**必须**用这些变量 + 回退逻辑（模块被单独执行时也能用）：

```sh
RUNTIME="${OFFICE_KIT_RUNTIME:-$(cd "$(dirname "$0")/../../runtime" && pwd)}"
```

### 2.2 通用输出约定

- 人类可读输出默认写 **stdout**；诊断/进度写 **stderr**。
- 每个命令都支持 `--json`：输出单个 JSON 对象（UTF-8，不转义中文），字段稳定。
- 成功退出码 0；参数错误 2；运行时错误 1；缺依赖 3（并打印可执行的修复提示）。
- 绝不在运行时联网；不调用系统 pip/npm；不假定系统装了 `soffice`/`java`/`tesseract`。

### 2.3 各模块子命令（必须实现）

**office**（`modules/office/bin/office`）
```
office convert --input F --output F [--json]          # docx/xlsx/pptx/odt/... -> pdf
office render  --input F --output-dir D [--pages 1,3] [--dpi 144] [--json]
office recalc  --input F --output F [--json]          # xlsx 公式重算
office info    --input F [--json]                     # 结构摘要（段落/表/页/工作表）
office create  --type docx|xlsx|pptx --output F --plan plan.json [--json]
```
`create` 用 `$OFFICE_KIT_PY` + python-docx/openpyxl/python-pptx 生成；`plan.json` 的
schema 由你定义并在 SKILL.md 写清楚（保持简单、可组合）。

**pdf**（`modules/pdf/bin/pdf`）
```
pdf start|stop|status
pdf run <tool> --input ... --output ... [--option k=v ...] [--json]
pdf list-tools [--json]
```
`run` 通过 Stirling REST API 调用；`start` 按需拉起 headless 后端（不启动 Electron），
端口写入 `$OFFICE_KIT_DATA/pdf/`，带就绪等待、复用与空闲退出。至少覆盖并 test：
merge、split(pages)、rotate、extract-text、pdf-to-img、img-to-pdf、compress、
encrypt、decrypt、watermark、ocr(带 tesseract chi_sim)、pdf-to-pdfa、info。

**ofd**（`modules/ofd/bin/ofd`）
```
ofd info --input F [--json]
ofd to-pdf --input F --output F [--json]
ofd to-image --input F --output-dir D [--dpi 144] [--json]
ofd to-text --input F [--json]
ofd to-html --input F --output D [--json]
ofd merge --input A --input B --output F [--json]
ofd from-pdf --input F --output F [--json]   # 若 ofdrw 版本不支持则显式报 3 并说明
```
基于 ofdrw + `$OFFICE_KIT_JAVA`。Java 源码放 `modules/ofd/src/`，构建产物（jar + 依赖）
放 `modules/ofd/lib/`，`modules/ofd/build.sh` 可重建（构建时联网，运行时不联网）。

**ocr**（`modules/ocr/bin/ocr`）
```
ocr image --input F [--lang chi_sim+eng] [--engine auto|rapid|tess] [--json]
ocr pdf   --input F [--pages 1-3] [--lang ...] [--json]
ocr batch --input DIR [--json]
ocr list-langs [--json]
```
默认引擎 RapidOCR(ONNX，中英)；tesseract 作为可选后备（系统若有）。输出 JSON 必须含
`text` 以及按行/块的 `lines[{text,box,score}]`，便于模型做版面分析。
PDF 逐页渲染用内置 PyMuPDF 或 `runtime` 自带能力，不依赖系统 poppler。

**asr**（`modules/asr/bin/asr`）
```
asr file --input F [--format text|srt|json] [--json]
asr mic  [--seconds N] [--format text|json] [--json]
asr listen [--device D] [--once] [--json]     # 连续听写，一行一句，用于“语音输入”
asr input  [--device D]                       # 识别后写剪贴板并尝试自动粘贴
asr devices [--json]
asr models [--json]
```
基于 `$OFFICE_KIT_MODELS/llama/llama-funasr-sensevoice -m sensevoice-small-q8.gguf -a x.wav`。
录音用 `arecord`/`ffmpeg`（目标机一般有）；采样率 16k 单声道；`listen` 用静音检测切分。
`input` 在 xclip/wl-copy 存在时写剪贴板，ydotool/xdotool 存在时尝试 Ctrl+V，缺工具时降级为打印。

## 3. 技能（SKILL.md）要求

- 目录 `skills/<skill>/`，frontmatter **必须**有 `name`（与目录同名）和 `description`。
- description 用中文，写清“什么时候用 + 关键能力 + 一句触发词”，不超过 500 字。
- 正文必须包含：
  1. 何时使用 / 不适用；
  2. 前置检查：`office-kit --version`、`office-kit <group> ... --help`；
  3. 3~5 个真实可运行的命令示例（相对路径 + 中文说明）；
  4. 输出解读（JSON 字段）；
  5. 常见错误与处理（缺模型、端口占用、字体缺失、扫描件无文本等）；
  6. 离线边界说明（不会联网）。
- 正文里的命令必须**实际跑通**（用 `test.sh` 验证）。
- `LICENSES.md` 列出所用上游项目、版本、许可证（LibreOffice MPL-2.0、Stirling-PDF MIT、
  ofdrw Apache-2.0、SenseVoice/llama.cpp MIT/Apache、RapidOCR Apache-2.0、tesseract Apache-2.0 等）。

## 4. 质量门禁

每个模块交付前必须：

1. `bash modules/<group>/test.sh` 通过（测试数据可留在 `modules/<group>/testdata/`，小文件）；
2. 断网语义：测试中不访问网络（可用 `http_proxy=http://127.0.0.1:9 https_proxy=...` 验证）；
3. `office-kit <group> --help` 有清晰帮助；
4. 读写只发生在 `$OFFICE_KIT_DATA` 与用户指定的输出路径；
5. 路径含中文/空格可用（用引号，别用 `eval`）。

## 5. 协作规则

- 只改自己的 `modules/<group>/`、`skills/<skill>/`；共享文件（`bin/office-kit`、
  `build/`、`runtime/`、`README.md`）由主智能体维护，需要改就发消息说明。
- 遇到运行时缺依赖（Python wheel / jar / 模型），可联网补装到自己的 `modules/<group>/lib/`，
  并在 README 记录来源，**不要**污染 `runtime/python` 的 site-packages（如确实需要，先问主智能体）。
- 自测产生的临时文件放 `$KIT/.tmp/<group>/`。
