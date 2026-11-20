# 从源码构建

仓库只包含**源码、技能与文档**；`runtime/`（约 1.4 GB 的 JRE/Node/Python/Stirling/
模型）和 `dist/*.AppImage` 不进 Git，通过 Release 分发，或在构建机本地组装。

## 0. 环境

| 项 | 要求 |
| --- | --- |
| 架构 | aarch64（x86_64 需自行替换各引擎产物） |
| 系统 | Kylin V10 / UOS ARM，glibc ≥ 2.31 |
| 构建期网络 | 需要（npm / PyPI / Maven / 模型下载），运行期不需要 |
| 磁盘 | 约 5 GB（runtime + AppDir + 产物） |
| 工具 | git、Node 22、Python 3.12、JDK 21 + Maven（仅 OFD 模块） |

## 1. 获取源码

```sh
git clone https://github.com/<you>/office-kit.git
cd office-kit
```

## 2. 准备 runtime/

### 方式 A：从已有 AppImage 解包（最快，推荐）

如果你已经有一个可用的 `office-kit-*.AppImage`：

```sh
chmod +x office-kit-1.0.0-linux-arm64.AppImage
./office-kit-1.0.0-linux-arm64.AppImage --appimage-extract
cp -a squashfs-root/usr/share/office-kit/runtime ./runtime
cp -a squashfs-root/usr/share/office-kit/modules ./modules   # 含 OFD jar 与 class
```

解包后 `runtime/` 就位，可直接跳到第 3 步。

### 方式 B：从零组装

`runtime/` 的目录契约：

```
runtime/
├── jre/        Temurin JDK 25 jlink 运行时（bin/java，含 java.desktop/xml/sql）
├── node/       Node 22 + lib/node_modules/@deepseek-ai/libreoffice-kit{,-wasm}
├── python/     CPython 3.12 + site-packages
├── stirling/   Stirling-PDF.jar + native/(jpdfium) + tessdata/
├── models/     sensevoice/sensevoice-small-q8.gguf + llama/llama-funasr-sensevoice
└── glibc/      lib/ld-linux-aarch64.so.1 + lib/*.so（供 jpdfium 使用）
```

| 组件 | 来源 | 放置 |
| --- | --- | --- |
| Node 22 | nodejs.org 官方 aarch64 压缩包 | `runtime/node/bin/node` |
| LibreOffice WASM | `npm i @deepseek-ai/libreoffice-kit@0.1.5 @deepseek-ai/libreoffice-kit-wasm@0.1.5` | `runtime/node/lib/node_modules/` |
| CPython 3.12 | python-build-standalone（astral-sh） | `runtime/python/` |
| Python 依赖 | `pip install python-docx openpyxl python-pptx pymupdf pillow numpy onnxruntime opencv-python-headless rapidocr_onnxruntime pyyaml xlwt` | `runtime/python/lib/python3.12/site-packages/` |
| Stirling-PDF | 官方 jar 3.1.0 + jpdfium 原生库 + tessdata（chi_sim/eng/osd） | `runtime/stirling/` |
| JRE | Temurin 21/25 `jlink --add-modules java.base,java.desktop,java.xml,java.sql,...` | `runtime/jre/` |
| SenseVoice | ModelScope `iic/SenseVoiceSmall` 转 GGUF Q8，约 243 MB | `runtime/models/sensevoice/` |
| llama-funasr | asr-now 项目的 aarch64 可执行 | `runtime/models/llama/` |
| glibc | 从 Stirling 桌面版 AppImage 解包（或任意 glibc ≥ 2.35 的 aarch64 rootfs） | `runtime/glibc/` |

> 四个 Python 依赖和两个模型是离线能力的关键，务必确认 `rapidocr_onnxruntime/models/`
> 与 `sensevoice-small-q8.gguf` 都已落地。

### OFD 依赖

```sh
bash modules/ofd/build.sh      # 自动下载 JDK21 + Maven，拉 ofdrw 2.5.1 依赖并编译
```

产物在 `modules/ofd/lib/{jars,classes}`（本仓库不提交，需构建一次）。

## 3. 构建 AppImage

```sh
bash build/build-appimage.sh
# 产物: dist/office-kit-1.0.0-linux-arm64.AppImage + .sha256
```

需要 `appimagetool-aarch64.AppImage` 与 type-2 runtime。脚本默认读取
`/home/link/桌面/code/stirling-desktop-build/downloads/`，可用环境变量覆盖：

```sh
APPIMAGETOOL=/path/to/appimagetool-aarch64.AppImage \
APPIMAGE_RUNTIME=/path/to/runtime-aarch64 \
bash build/build-appimage.sh
```

## 4. 验收

```sh
bash modules/office/test.sh
bash modules/pdf/test.sh
bash modules/ofd/test.sh
bash modules/ocr/test.sh
bash modules/asr/test.sh
bash test/integration.sh                                  # 仓库模式
KIT_APPIMAGE=dist/office-kit-*-linux-arm64.AppImage bash test/integration.sh   # AppImage 模式
```

前五条各自打印 `OK <模块>`，集成脚本打印 `PASS`（39 项）。

## 5. 发布到 GitHub Releases

AppImage 812 MB，超过 GitHub 单文件 100 MB 限制，**不要提交进 Git**，用 Release 附件：

```sh
gh release create v1.0.0 \
  dist/office-kit-1.0.0-linux-arm64.AppImage \
  dist/office-kit-1.0.0-linux-arm64.AppImage.sha256 \
  --title "office-kit 1.0.0" --notes-file dist/RELEASE-1.0.0.md
```

或在网页端 *Releases → Draft a new release* 手动上传。
