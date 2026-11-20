---
name: ofd-tools
description: 处理国产版式文档 OFD（电子发票、财政票据、公文、证照）的离线工具：查看版本/页数/页面尺寸/字体/签名/文本块，转 PDF、逐页 PNG、逐页文本（带坐标）、自包含 HTML，合并多份 OFD，以及 PDF 转 OFD。当用户给出 .ofd 文件，或提到 OFD、版式文档、ofd 转 pdf/图片/文本时使用。
---

# OFD 版式文档工具（ofd-tools）

OFD 是 GB/T 33190-2016 定义的国产版式文档，常见于电子发票、财政票据、公文、证照。
本技能基于 ofdrw 2.5.1 + `runtime/jre`，可完全离线地读取、转换、合并 OFD。

## 1. 何时使用 / 不适用

**使用：**

- 用户给的是 `.ofd` 文件（发票、票据、公文、证照、电子合同）；
- 需要把 OFD 转成 PDF 归档、转成 PNG 预览/贴图、抽取文字交给模型阅读；
- 需要把多份 OFD 按顺序合并成一份；
- 需要确认 OFD 的页数、页面尺寸、文档 ID、是否含签名、文本是否可提取；
- 需要把 PDF 反向转成 OFD（文字可检索优先）。

**不适用：**

- 普通 PDF → 用 `pdf-tools`；Word/Excel/PPT → 用 `office-docs`；
- 扫描件图片的 OCR → 用 `ocr-tools`（本技能只读取 OFD 自带文字层）；
- **加密 OFD**（包内含 `Encryptions.xml`）：ofdrw 不支持解密，需先用签发系统导出未加密副本；
- 需要验证电子签章有效性：`info` 只列出签名 ID，不做验签。

## 2. 前置检查

```bash
office-kit --version                 # 1.0.0 可用
office-kit ofd --help               # 应列出 info/to-pdf/to-image/to-text/to-html/merge/from-pdf
ls -l 发票.ofd                      # 确认文件存在且非空
```

- 若报 `模块尚未构建`（退出码 3）：在联网构建机执行 `bash modules/ofd/build.sh`。
- 若报 `找不到 Java 运行时`（退出码 3）：检查 `runtime/jre` 或 `OFFICE_KIT_JAVA`。
- 中文/空格路径可直接用引号传入：`office-kit ofd info --input "发票 2026.ofd"`。

## 3. 常用命令（相对路径，均已验证）

以下示例先准备一个自带中文的演示 OFD；有真实文件时把 `.tmp/ofd/演示.ofd` 换成实际路径即可。

```bash
mkdir -p .tmp/ofd
office-kit ofd demo --output .tmp/ofd/演示.ofd   # 生成 2 页含中文的样例（自检用）
```

### 3.1 看文档信息（先跑这个）

```bash
office-kit ofd info --input .tmp/ofd/演示.ofd --json
```

输出版本、页数、每页尺寸（mm）、DocID、签名数量、字体列表（`embedded` 是否内嵌）、
文本块数量。转 PDF 前先看 `fonts[].embedded`，未内嵌时中文可能依赖系统字体。

### 3.2 OFD 转 PDF

```bash
office-kit ofd to-pdf --input .tmp/ofd/演示.ofd --output .tmp/ofd/演示.pdf --json
```

PDF 页数与 OFD 一致，内嵌字体会写入 PDF；`pages` 是复核后的实际页数。
适合归档、打印、发给只认 PDF 的系统。
注意：ofdrw 按“整字体嵌入”写 PDF，只引用系统字体的发票转出的 PDF 可能有 20~40 MB；
需要小体积预览请用 `to-image`，或再交给 `pdf-tools` 压缩。

### 3.3 OFD 转逐页 PNG

```bash
office-kit ofd to-image --input .tmp/ofd/演示.ofd --output-dir .tmp/ofd/png --dpi 144 --json
```

生成 `png/page-001.png`、`png/page-002.png`，默认 144 dpi。贴图/预览用 144，
打印稿可用 `--dpi 300`（页面大时加 `OFFICE_KIT_JAVA_OPTS=-Xmx2g`）。
`images[].width/height` 给出像素尺寸。

### 3.4 抽取逐页文本与坐标（给模型做版面分析）

```bash
office-kit ofd to-text --input .tmp/ofd/演示.ofd --json
```

JSON 里 `pages[].lines[].text` 是文字，`box:[x,y,w,h]` 是页面左上角起算的毫米坐标，
`size` 是字号（mm）。扫描件 OFD 没有文字层时 `lines` 为空数组（不是错误）。

### 3.5 合并多份 OFD

```bash
office-kit ofd merge --input .tmp/ofd/演示.ofd --input .tmp/ofd/演示.ofd \
  --output .tmp/ofd/合并.ofd --json
```

按 `--input` 出现顺序拼接，至少 2 个输入；字体/图片/印章资源会一起迁移。
合并后 `pages` 为总页数，可再用 `info` 复核。

### 3.6 生成可浏览器预览的 HTML

```bash
office-kit ofd to-html --input .tmp/ofd/演示.ofd --output .tmp/ofd/html --json
```

目录下生成单文件 `index.html`（内联 SVG + 透明文字层，可选中复制），不依赖外部资源，
可直接发给浏览器打开。

### 3.7 PDF 转 OFD

```bash
office-kit ofd from-pdf --input .tmp/ofd/演示.pdf --output .tmp/ofd/回环.ofd --json
office-kit ofd from-pdf --input 合同.pdf --output 合同.ofd --mode graphics --json
```

`--mode auto`（默认）优先“文字对象化”（`text_searchable: true`，文本可检索）；若 PDF
字体无法嵌入，或 ofdrw 写出的文字坐标异常（已观察到部分 PDF 行距为负、文字堆叠），
会自动回退图形化（`engine: "graphics"`、`text_searchable: false`，版式保真但文本不可检索），
并在 JSON 中给 `fallback_reason`。`--mode text` 强制文字对象化，`--mode graphics` 强制图形化。

## 4. JSON 字段速查

| 命令 | 关键字段 |
| --- | --- |
| `info` | `pages`、`page_sizes`（mm）、`version`、`doc_type`、`doc_id`、`title`、`author`、`signatures{count,ids}`、`fonts[{name,family,embedded}]`、`text_blocks`、`attachments`、`encrypted`、`file_size` |
| `to-pdf` | `input`、`output`、`pages`、`file_size`、`engine` |
| `to-image` | `output_dir`、`dpi`、`pages`、`images[{file,page,width,height}]` |
| `to-text` | `page_count`、`line_count`、`pages[{page,size,lines[{text,box,size}]}]` |
| `to-html` | `output_dir`、`index`、`pages`、`file_size`、`self_contained` |
| `merge` | `inputs[]`、`output`、`pages`、`file_size` |
| `from-pdf` | `output`、`pages`、`file_size`、`engine`、`text_searchable`、`mode`、`fallback_reason`（回退时） |

所有命令都支持 `--json`：成功时 stdout 只有一个 JSON 对象（UTF-8，中文不转义）；
错误只写 stderr，退出码：0 成功 / 2 参数错误 / 1 运行时错误 / 3 缺依赖。

## 5. 常见错误与处理

| 现象 | 原因 / 处理 |
| --- | --- |
| `该 OFD 文档已加密（包含 Encryptions.xml）`，退出码 1 | ofdrw 不解密。用开票/签发系统导出未加密 OFD，或让用户提供 PDF/图片。 |
| `不是有效的 OFD 文件（缺少 ZIP 容器标识）`，退出码 1 | 文件实际是 PDF/图片或扩展名被改；用 `file 文件` 确认格式，PDF 改用 `pdf-tools`。 |
| `无法解析 OFD 文件（… Truncated ZIP file）`，退出码 1 | 下载/传输损坏，重新获取原文件。 |
| `info` 显示 `fonts[].embedded:false`，转 PDF 后中文变方框/缺字 | OFD 只引用了系统字体名。`to-pdf` 会尝试系统字体；仍不行时用原签发系统“打印为 PDF”，或换带内嵌字体的 OFD。 |
| 转 PDF 后中文像随机拉丁字母 | 该 OFD 内嵌的是 CFF/OTF 子集字体，ofdrw PDF 管线可能字形错位；改用 `to-image`（另一种渲染路径）或向签发方索取 TrueType 内嵌版本。 |
| 页数与预期不符 | OFD 可含多个 `DocBody`，ofdrw 只读默认文档；也可能是合并/插入页导致。用 `info` 的 `pages`、`to-text` 的 `page_count` 交叉确认。 |
| to-pdf 生成 PDF 特别大（20~40 MB） | ofdrw 整字体嵌入（设计决策 16），不是失败；要小体积改用 `to-image` 或 `pdf-tools` 的 compress。 |
| `内存不足` / 大页面 300 dpi 失败 | 提高 JVM 上限：`OFFICE_KIT_JAVA_OPTS="-Xmx2g" office-kit ofd to-image …`，或降低 `--dpi`。 |
| `输入文件不存在`，退出码 2 | 路径写错或含未转义空格；用引号包住路径。 |
| `merge 至少需要两个 --input`，退出码 2 | 合并至少给 2 个 `--input`；单个文件复制用 `cp` 即可。 |
| `from-pdf` 返回 `text_searchable:false` | PDF 字体不可嵌入，或文字坐标异常，已自动回退图形化；能看不能搜。需要可检索时可试 `--mode text`，但要检查排版是否正确。 |
| `from-pdf` 提示“文字坐标异常…回退图形化” | ofdrw 2.5.1 的 PDF 文本定位限制（负行距/越界）。默认结果视觉正确但不可检索；需要文本层可加 `--mode text` 并人工复核。 |
| `模块尚未构建` / `找不到 Java 运行时`，退出码 3 | 构建机执行 `bash modules/ofd/build.sh`；或设置 `OFFICE_KIT_JAVA`。 |
| 退出码 2 且提示 `--dpi 必须在 36~1200` | 调整 DPI 到合理范围（144/200/300）。 |

## 6. 离线边界

- 本技能**不会联网**：OFD 解析、字体嵌入、PDF/图片/HTML 生成全部在本机完成，
  文件不会上传到任何服务；`test.sh` 用 `http_proxy=http://127.0.0.1:9` 强制断网验证。
- 运行期不调用系统 `java`、`soffice`、`pip`、`npm`；只读 `runtime/` 与自身 `lib/`。
- 中间文件只写入 `$OFFICE_KIT_CACHE/ofd/tmp` 与用户指定的输出路径；
  可用 `OFFICE_KIT_CACHE` 改位置，异常退出后的临时目录会在后续运行中清理。
- 转换有损：复杂图形、印章、艺术字、非内嵌字体的 OFD 可能样式偏移；对保真要求高时，
  先 `to-pdf` 对比原件，或保留 OFD 原文件。

## 方向速查：PDF ↔ OFD

这是最常见的一处误用，先看方向再选命令：

| 想要 | 正确命令 |
| --- | --- |
| OFD → PDF | `office-kit ofd to-pdf --input 公文.ofd --output 公文.pdf` |
| PDF → OFD | `office-kit ofd from-pdf --input 公文.pdf --output 公文.ofd` |
| OFD → 图片 | `office-kit ofd to-image --input 公文.ofd --output-dir 预览 --dpi 144` |
| OFD → 文本 | `office-kit ofd to-text --input 公文.ofd --json` |
| OFD → HTML | `office-kit ofd to-html --input 公文.ofd --output 网页/` |
| PDF 合并/加密/抽文本 | `office-kit pdf run ...`（不是 ofd） |

`to-pdf` 的输入必须是 OFD。若误把 PDF 交给 `to-pdf`，CLI 会直接提示正确命令并以退出码 2
结束（不会把 PDF 丢给 ZIP 解析器报 `Cannot find zip signature`）。同理 `from-pdf` 只接受 PDF。

`from-pdf` 默认 `--mode auto`：ofdrw 2.5.1 的文字对象化在部分 PDF 上会出现负 DeltaY，
此时自动回退为图形化 OFD（版式保真、文本不可检索），JSON 里给出 `engine:"graphics"` 与
`fallback_reason`；需要可检索文本时用 `--mode text`，但版面可能有偏差。

## 命令入口（离线机必读）

本技能假设 `office-kit` 已在 `PATH` 中。若执行时报 `command not found`，改用 AppImage 绝对路径：

```sh
KIT="${OFFICE_KIT_BIN:-$HOME/apps/office-kit.AppImage}"
"$KIT" --version
```

后文所有 `office-kit <分组> ...` 都可以等价替换为 `"$KIT" <分组> ...`。
AppImage 需要 `chmod +x`；若提示 FUSE 不可用，加环境变量 `APPIMAGE_EXTRACT_AND_RUN=1`。
