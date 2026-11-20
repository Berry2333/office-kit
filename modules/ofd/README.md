# modules/ofd — OFD 版式文档模块（Java / ofdrw）

国产版式文档 **OFD**（GB/T 33190-2016，电子发票 / 财政票据 / 公文 / 证照）的离线处理模块。
后端为 Java，基于 [ofdrw 2.5.1](https://github.com/ofdrw/ofdrw)（Apache-2.0），运行时使用
`runtime/jre`（Temurin 25 jlink），**不联网、不依赖系统 Java / LibreOffice / Python 包**。

- 入口：`modules/ofd/bin/ofd`（也可经 `office-kit ofd ...` 调用）
- 源码：`modules/ofd/src/ofdkit/*.java`（17 个类）
- 产物：`modules/ofd/lib/classes/`（class）+ `modules/ofd/lib/jars/`（39 个 jar，约 28 MB）
- 构建：`bash modules/ofd/build.sh`（构建期联网，下载 JDK 21 / Maven / Maven 依赖）
- 自检：`bash modules/ofd/test.sh`（成功打印 `OK ofd`，全程断网代理）

## 1. 子命令

| 子命令 | 作用 | 主要参数 |
| --- | --- | --- |
| `info` | 版本、页数、每页尺寸（mm）、文档 ID、签名、字体（含是否内嵌）、文本块、附件 | `--input F [--json]` |
| `to-pdf` | OFD → PDF（ofdrw PDFBox 渲染管线） | `--input F --output F [--json]` |
| `to-image` | 逐页 PNG（`page-001.png`…），默认 144 dpi | `--input F --output-dir D [--dpi 144] [--json]` |
| `to-text` | 逐页文本 + 文字框坐标（mm） | `--input F [--json]` |
| `to-html` | 目录下生成自包含 `index.html`（内联 SVG + 可选中文字层） | `--input F --output D [--json]` |
| `merge` | 按输入顺序合并 ≥2 个 OFD | `--input A --input B [--input C …] --output F [--json]` |
| `from-pdf` | PDF → OFD（auto：优先文字对象化，异常时回退图形化） | `--input F --output F [--mode auto\|text\|graphics] [--json]` |
| `demo` | 隐藏自检命令：生成 2 页含中文的演示 OFD | `--output F [--font TTF] [--json]` |

通用：`--json`（单个 JSON 对象写 stdout，中文不转义）、`--help`、`-V/--version`。

### JSON 字段（稳定）

```jsonc
// info
{"input":"/abs/发票.ofd","file_size":45094,"pages":2,"page_units":"mm",
 "page_sizes":[[210,297],[210,297]],"version":"1.2","doc_type":"OFD",
 "doc_id":"…32位hex…","title":"","author":"","subject":"","creator":"OFD R&W",
 "creator_version":"2.5.1","creation_date":"2026-11-20","mod_date":"",
 "signatures":{"count":0,"ids":[]},
 "fonts":[{"name":"宋体","family":"宋体","embedded":true,"bold":false,"italic":false}],
 "text_blocks":33,"attachments":0,"encrypted":false}

// to-pdf
{"input":"…","output":"…","pages":2,"file_size":56030,"engine":"ofdrw-2.5.1/PDFBox-3.0.8"}

// to-image
{"input":"…","output_dir":"…","dpi":144,"pages":2,
 "images":[{"file":"page-001.png","page":1,"width":1190,"height":1683}, …]}

// to-text
{"input":"…","page_count":2,"line_count":21,
 "pages":[{"page":1,"size":[210,297],
           "lines":[{"text":"电子发票（普通发票）","box":[20,28.43,80,8],"size":8}]}]}

// to-html
{"input":"…","output_dir":"…","index":"…/index.html","pages":2,"file_size":167597,"self_contained":true}

// merge
{"inputs":["a.ofd","b.ofd"],"output":"ab.ofd","pages":4,"file_size":44430}

// from-pdf
{"input":"…","output":"…","pages":2,"file_size":48951,
 "engine":"text-object|text-object-outlined|graphics","text_searchable":false,
 "mode":"auto",                         // 发生回退时才有的字段：
 "fallback_reason":"text geometry suspicious"}
```

`to-text` 的 `box` 为 `[x, y, w, h]`：单位 mm，页面左上角为原点；`size` 是字号（mm）。
`x/y` 来自 TextObject/TextCode 的边界与坐标，属于**近似字形框**（旋转文字、艺术字可能不精确）。

### 退出码

| 码 | 含义 | 示例 |
| --- | --- | --- |
| 0 | 成功 | — |
| 2 | 参数错误 | 缺 `--input`/`--output`、`--dpi` 非法、merge 输入 <2、输出与输入同路径 |
| 1 | 运行时错误 | OFD 损坏、非 OFD、加密 OFD、PDF 加密、字体缺失导致转换失败、内存不足 |
| 3 | 缺依赖 | 找不到 `OFFICE_KIT_JAVA`、模块未构建（缺 `lib/classes` 或 `lib/jars`） |

错误信息只写 stderr；`--json` 成功时 stdout 只有一个 JSON 对象。

## 2. 环境变量

| 变量 | 用途 |
| --- | --- |
| `OFFICE_KIT_JAVA` | Java 可执行文件，默认 `$OFFICE_KIT_RUNTIME/jre/bin/java` |
| `OFFICE_KIT_JAVA_OPTS` | JVM 参数，默认 `-Xmx1g`；300 dpi 以上大页面建议 `-Xmx2g` |
| `OFFICE_KIT_CACHE` | 临时目录根；实际使用 `$OFFICE_KIT_CACHE/ofd/tmp` |
| `OFFICE_KIT_ROOT` / `OFFICE_KIT_RUNTIME` | 仓库根 / runtime 根（模块单独执行时自动回退推断） |
| `OFD_DEMO_FONT` | `ofd demo` 使用的 TTF 字体路径（可选） |
| `OFD_DEBUG` | `1` 时打印 Java 异常堆栈（诊断用） |

`bin/ofd` 会固定 `-Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8 -Djava.awt.headless=true`，
并把 `java.io.tmpdir` 指到 `OFFICE_KIT_CACHE/ofd/tmp`，避免 OFDReader 解压污染 `/tmp`。

## 3. 构建

```bash
bash modules/ofd/build.sh
```

构建脚本会：

1. 若 `.tmp/ofd/jdk/bin/javac` 不存在，下载 Temurin JDK 21（约 206 MB）到 `.tmp/ofd/jdk`；
2. 若 `.tmp/ofd/maven/bin/mvn` 不存在，下载 Maven 3.9.16 到 `.tmp/ofd/maven`；
3. `mvn clean package`：`src/` → `lib/classes/`，`dependency:copy-dependencies` → `lib/jars/`；
4. 校验 class/jar 数量并清理 `target/`。

构建期用到的 JDK、Maven、`~/.m2` 缓存（脚本默认 `.tmp/ofd/m2`）都**不入库**；仓库里只保留
`lib/classes` 与 `lib/jars` 运行产物。可用 `OFD_JDK` / `OFD_MVN` / `OFD_M2` 覆盖路径，
`OFD_NO_DOWNLOAD=1` 禁止构建期下载。

构建依赖（`pom.xml`）：

- `org.ofdrw:ofdrw-converter:2.5.1`（转 PDF / HTML / OFD）
- `org.ofdrw:ofdrw-layout:2.5.1` + `ofdrw-core` + `ofdrw-reader`（生成 / 读取）
- `org.ofdrw:ofdrw-tool:2.5.1`（`OFDMerger`）
- 传递依赖：PDFBox 3.0.8、Batik 1.19、BouncyCastle 1.85、dom4j、commons-compress、zip4j 等；
- 额外显式加入 `org.slf4j:slf4j-nop:1.7.36`，静默 ofdrw 内部日志（避免污染 stderr）。

## 4. 实现说明

- **info**：`OFDReader.getOFDDir().getOfd()` 读 `OFD.xml`（Version/DocType）、`DocBody/DocInfo`
  （DocID/标题/作者/日期），页面尺寸用 `getPageSize(i)`（mm），签名用
  `getDefaultSignatures()`（只列出，不验签），字体来自 `getResMgt().getFonts()`，
  文本块递归遍历 `PageInfo.getAllLayer()`（含模板层）。
- **to-pdf**：`ConvertHelper.toPdf(Path, Path)`，产物先用临时文件写，再用 PDFBox 复核页数后
  原子替换，失败不会留下半个 PDF。注意 ofdrw 2.5.1 按“整字体嵌入”（设计决策 16）写 PDF：
  OFD 只引用系统字体时，PDF 会嵌入完整中文字体，**单页发票转出的 PDF 可能有 20~40 MB**。
  需要小体积预览请用 `to-image`，或再交给 `pdf-tools` 的 compress。
- **to-image**：先转 PDF（与 to-pdf 同一渲染管线，保证字体/印章一致），再用 PDFBox
  `PDFRenderer.renderImageWithDPI` 按 DPI 输出 RGB PNG；`--dpi` 36~1200。
- **to-text**：直接遍历 OFD 页面树（含模板），把每个 `TextObject/TextCode` 输出为一行；
  宽度优先用 `DeltaX` 推算，单 TextCode 时用对象边界，最后按字号比例估算；无文本层时
  返回空 `lines`（扫描件 OFD 常见），不报错。
- **to-html**：`ConvertHelper.toHtml(Path, Path, 1000)` 生成单文件 HTML；随后删除内嵌 SVG 的
  `<?xml?>` / `<!DOCTYPE svg>`（浏览器中属于非法 HTML），并把 `lang`/`title` 改为中文。
  可见内容为 SVG 路径，文字层为透明 `<text>`（可选中复制）。
- **merge**：`org.ofdrw.tool.merge.OFDMerger` 按 `--input` 顺序 `add`，`close()` 时打包；
  合并后自动重开复核页数。
- **from-pdf**：三种模式（`--mode auto|text|graphics`，默认 auto）。
  1. 先尝试 `PDFConverter`（文字对象化，内嵌字体，文本可检索）；
  2. 若字体无法嵌入而抛错，或产物的文字几何明显异常（负 `DeltaY`、Boundary 越界——
     ofdrw 2.5.1 在部分 PDF 上的文本定位缺陷），auto 模式会删掉半成品并改用
     `PDFGraphicsConverter`（整页图形化，版式保真但文本不可检索），stderr 给出原因；
  3. 转换后重新抽取文本，`text_searchable` 以实际产物为准；加密 PDF 明确报错（退出码 1）。
  `--mode text` 可强制保留文字对象（即使可能错位），`--mode graphics` 强制图形化。
- **加密 OFD**：检测 ZIP 内 `Encryptions.xml`，直接报错并提示用签发系统导出未加密副本
  （ofdrw 不解密）。
- **路径**：全流程 `Path` + UTF-8，中文/空格路径已覆盖测试；不使用 `eval`。

### 演示字体（`testdata/fonts/ofd-demo-cjk.ttf`）

`ofd demo` 需要可嵌入的中文字体。仓库内自带 41 KB 的 `OfficeKit Demo CJK`，由
**Droid Sans Fallback（汉字，Apache-2.0）+ DejaVu Sans（ASCII/数字/¥，Bitstream Vera）**
子集合并而成，仅包含 `testdata/demo-chars.txt` 中的字符。重新生成（构建期，需 fontTools）：

```bash
pip install fonttools                    # 构建期依赖，运行期不需要
pyftsubset /usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf \
  --text-file=modules/ofd/testdata/demo-chars.txt --output-file=/tmp/cjk.ttf
pyftsubset /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf \
  --text-file=/tmp/latin-chars.txt --output-file=/tmp/latin.ttf
# 用 fontTools.ttLib.scaleUpem 把 Droid 的 unitsPerEm 256 → 2048，再 Merger().merge([latin, cjk])
```

字体许可见 `testdata/fonts/LICENSE.txt`。**只用于演示 OFD**，不参与用户文档的字体替换。

## 5. 测试

```bash
bash modules/ofd/test.sh
```

`test.sh` 设置 `http_proxy/https_proxy=127.0.0.1:9` 强制断网，覆盖：

1. `ofd demo` 生成含中文、2 页、内嵌字体的 OFD（中文+空格路径）；
2. `info`：版本、页数、页面尺寸、DocID、字体内嵌、文本块、签名、加密字段；
3. `to-pdf`：PyMuPDF（`$OFFICE_KIT_PY`）打开，页数=2、文本含“电子发票/价税合计/第二页/office-kit”，
   首页非空白渲染；
4. `to-image`：`page-001.png`/`page-002.png` 存在且 PNG 尺寸 1190×1683（A4@144dpi）；
5. `to-text`：逐页文本含预期中文，`box` 为 4 元组且坐标有效；
6. `to-html`：`index.html` 含 2 个 `svgItem`、SVG、中文 lang，且 XML 声明被清理；
7. `merge`：2+2=4 页，JSON 与重新读取的页数一致；
8. `from-pdf`：PDF→OFD 2 页；文字可检索时校验回环中文，auto 回退图形化时校验 `engine=graphics` 与 `fallback_reason`；
9. 错误码：文件不存在=2、非 OFD=1、加密 OFD=1、merge 单输入=2、缺 `--output`=2；
10. `bin/office-kit` 集成入口（若存在）：`office-kit ofd info` 与 `office-kit ofd --help` 可用。

成功输出最后一行：`OK ofd`（完整跑完约 30~60 秒，取决于机器）。

## 6. 已知限制

- **加密 OFD 不支持**（ofdrw 无解密实现）；报错退出码 1。
- **签名只列不验**：`info` 输出签名数量与 ID，不做证书链 / 摘要校验。
- **CFF/OTF 子集字体的 PDF 渲染**：测试中发现，用 fontTools 子集化 Noto Sans CJK（CFF）
  后再嵌入 OFD，`to-pdf` 文本可提取但字形错位；改用 TrueType（glyf）字体子集正常。
  用户若遇到 OFD 转 PDF 后中文显示为奇怪拉丁字形，可优先排查该 OFD 内嵌的是否为 CFF 子集。
- **PDF → OFD 的文字定位**：ofdrw 2.5.1 的 `PDFConverter` 在部分 PDF（含 ofdrw 自己导出的
  PDF）上会把行间距写成负 `DeltaY`，文字在 OFD 中堆叠错位。`from-pdf` 默认 auto 检测到
  该情况会回退为图形化 OFD（视觉正确、文本不可检索）；需要文本可检索时可显式
  `--mode text`，但要自行检查版面。
- **文本坐标是近似值**；旋转文字、艺术字、复合对象（CompositeObject）内的文字不保证覆盖。
- **to-html** 的 SVG 由 ofdrw `SVGMaker` 生成，可见内容为字形路径；极大文档会生成数 MB 的
  单文件 HTML。
- 关闭 `to-image` 时不会清理输出目录中上一次遗留的 `page-*.png`（只覆盖同名文件）。
- **to-pdf 体积偏大**：见上，整字体嵌入导致中文字体完整写入 PDF；不是转换失败。对体积敏感
  的场景建议 `to-image`（PNG）或配合 `pdf-tools` 压缩。

## 7. 许可

本模块源码基于 ofdrw API 编写；第三方 jar 的版本与许可见
`skills/ofd-tools/LICENSES.md`。演示字体许可见 `testdata/fonts/LICENSE.txt`。
