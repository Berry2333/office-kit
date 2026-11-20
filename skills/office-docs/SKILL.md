---
name: office-docs
description: 离线创建、读取、转换与预览 Word/Excel/PPT（docx/xlsx/pptx 及 doc/odt/xls/ods/ppt/odp）。支持按 JSON plan 生成报告、表格、演示文稿，Office 转 PDF，逐页渲染 PNG，刷新 xlsx 公式缓存，读取段落/工作表/幻灯片/PDF 结构摘要，并支持 WPS 的 .wps/.et/.dps。需要生成中文办公文档、把文档转 PDF、检查版面预览或重算公式时使用。触发词：Word、Excel、PPT、文档转 PDF、渲染预览、公式重算、office-docs。
---

# office-docs：离线 Word / Excel / PowerPoint 文档技能

本技能通过 `office-kit office` 调用内置的 LibreOffice WASM 引擎与 Python 办公库，
**全程离线**，不依赖系统安装 LibreOffice、Java 或 Node。

## 何时使用

适合：

- 用结构化 JSON plan 生成中文 **Word 报告 / Excel 表格 / PPT 汇报**；
- 把 `doc/docx/odt/xls/xlsx/ods/ppt/pptx/odp` **转成 PDF**；
- 把文档**逐页渲染成 PNG** 做版面预览、截图交付；
- **刷新 xlsx 公式缓存**（公式保留，缓存值更新，便于下游读取数值）；
- 读取 docx/xlsx/pptx/pdf 的**结构摘要**（段落、表格、工作表、幻灯片、页数、元数据、缺失字体）。

不适合：

- PDF 合并/拆分/加密/水印/OCR → 用 `pdf-tools`；
- OFD 版式文档 → 用 `ofd-tools`；
- 图片/扫描件文字识别 → 用 `ocr-tools`；
- 语音转写 → 用 `asr-voice`；
- 复杂的 Word 修订、批注、宏、图表编辑（本技能覆盖常用生成与摘要，不替代完整 Office）。

## 前置检查

```sh
office-kit --version
office-kit list
office-kit office --help
office-kit office convert --help
```

预期：`office-kit --version` 打印版本；`office-kit office --help` 列出
`convert / render / recalc / info / create` 五个子命令。若提示缺少 Node/Python/引擎，
说明安装不完整，应先修复运行时（见 `modules/office/README.md`）。

工作目录需要可写；所有输出写到 `--output` / `--output-dir` 指定的位置，缓存写到
`$OFFICE_KIT_DATA`（默认 `~/.local/share/office-kit`）。

## 五个可运行场景

> 以下命令均在当前目录执行，使用中文与空格文件名。先建立演示目录：

```sh
mkdir -p 演示文档
```

### 场景 1：生成 Word 报告并转 PDF

```sh
cat > "演示文档/报告-plan.json" <<'JSON'
{
  "title": "2026 年第一季度工作报告",
  "subtitle": "离线办公套件",
  "author": "数据分析组",
  "font": "Noto Sans CJK SC",
  "headings": [
    {"level": 1, "text": "一、总体进展"},
    {"level": 2, "text": "1.1 关键指标"}
  ],
  "paragraphs": [
    "本季度完成离线办公套件 v1.0 的集成。",
    {"text": "重点：转换、渲染、重算全部离线可用。", "bold": true, "color": "C00000"},
    {"text": "支持中文与空格路径。", "bullet": true}
  ],
  "tables": [
    {
      "headers": ["模块", "状态", "说明"],
      "rows": [["office", "完成", "5 个子命令"], ["pdf", "进行中", "Stirling-PDF"]],
      "widths": [3, 2, 7]
    }
  ]
}
JSON
office-kit office create --type docx --output "演示文档/季度 报告.docx" --plan "演示文档/报告-plan.json" --json
office-kit office convert --input "演示文档/季度 报告.docx" --output "演示文档/季度 报告.pdf" --json
office-kit office info --input "演示文档/季度 报告.docx" --json
```

最小表格 plan（`widths`、`style`、`headerBold` 全部可省略）：

```sh
printf '%s' '{"title":"最小示例","tables":[{"headers":["项目","金额"],"rows":[["办公",123.45]]}]}' \
  | office-kit office create --type docx --output "演示文档/最小 表格.docx" --plan - --json
```

### 场景 2：生成 Excel 预算表、刷新公式并读取结构

```sh
cat > "演示文档/预算-plan.json" <<'JSON'
{
  "sheets": [
    {
      "name": "销售汇总",
      "rows": [
        ["月份", "金额", "同比"],
        ["1 月", 1200, 0.12],
        ["2 月", 1500, 0.18],
        ["合计", "=SUM(B2:B3)", null],
        ["平均", "=AVERAGE(B2:B3)", null]
      ],
      "widths": {"A": 14, "B": 18, "C": 12},
      "styles": {
        "A1:C1": {"bold": true, "fill": "DDEBF7", "align": "center"},
        "B2:B5": {"numberFormat": "#,##0.00"}
      },
      "freeze": "A2",
      "autofilter": "A1:C1"
    },
    {
      "name": "明细",
      "rows": [["订单", "客户"], ["A001", "北京 某某公司"]]
    }
  ]
}
JSON
office-kit office create --type xlsx --output "演示文档/预算 表.xlsx" --plan "演示文档/预算-plan.json" --json
office-kit office recalc --input "演示文档/预算 表.xlsx" --output "演示文档/预算 表-重算.xlsx" --json
office-kit office info --input "演示文档/预算 表-重算.xlsx" --json
```

`recalc` 后公式仍保留，`openpyxl.load_workbook(..., data_only=True)` 可读到缓存值
（合计 2700、平均 1350）。

### 场景 3：生成 PPT 并渲染预览图

```sh
cat > "演示文档/汇报-plan.json" <<'JSON'
{
  "title": "离线办公套件汇报",
  "slideSize": "16:9",
  "font": "Noto Sans CJK SC",
  "cover": {"title": "离线办公套件", "subtitle": "Word / Excel / PowerPoint"},
  "slides": [
    {
      "title": "能力概览",
      "bullets": ["转换 PDF", "渲染 PNG", {"text": "按页 / 按区域", "level": 1}, "公式重算"],
      "notes": "讲稿：先总览，再演示命令。"
    },
    {
      "title": "关键指标",
      "table": {"headers": ["指标", "数值"], "rows": [["转换成功率", "100%"], ["是否联网", "否"]]}
    }
  ]
}
JSON
office-kit office create --type pptx --output "演示文档/季度 汇报.pptx" --plan "演示文档/汇报-plan.json" --json
office-kit office render --input "演示文档/季度 汇报.pptx" --output-dir "演示文档/汇报 预览" --pages 1-2 --dpi 144 --json
```

### 场景 4：读取 PDF / 工作簿摘要

```sh
office-kit office info --input "演示文档/季度 报告.pdf" --json
office-kit office info --input "演示文档/预算 表-重算.xlsx" --json
```

### 场景 5：指定页渲染与追加字体目录

```sh
office-kit office render --input "演示文档/季度 报告.pdf" --output-dir "演示文档/PDF 预览" --pages 1 --dpi 96 --json
office-kit office render --input "演示文档/季度 报告.docx" --output-dir "演示文档/字体 预览" --dpi 96 --font-dir /usr/share/fonts --json
```

完成后输出目录中会有 `page-001.png`、`page-002.png`… 以及 `manifest.json`。

## plan schema（`create`）

通用参数：`--type docx|xlsx|pptx`、`--output F`、`--plan plan.json`（`-` 表示从 stdin 读）。
输出后缀必须与 `--type` 一致；未写后缀会自动补 `.docx/.xlsx/.pptx`。
未知字段不会导致失败，会写入 JSON 的 `warnings[]` 并在 stderr 提示；类型/范围错误则以
退出码 2 失败，并指出具体路径（如 `sheets[0].rows[2]`）。

### docx plan

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `title` | string | 文档标题（Title 样式），同时写入核心属性 |
| `subtitle` | string | 副标题（Subtitle 样式） |
| `author` / `subject` / `keywords` | string | 文档核心属性 |
| `font` | string | 应用到正文、标题等样式的字体名（含东亚字体设置） |
| `headings` | array | 标题，元素为 string 或 `{level:1-9, text}` |
| `paragraphs` | array | 段落，元素为 string 或段落对象（见下表） |
| `tables` | array | 表格对象（见下表） |
| `blocks` | array | 按顺序渲染的块；**提供后 headings/paragraphs/tables 被忽略** |

> 除 `headers` / `rows` 外，表格的 `style`、`widths`、`headerBold` 都可省略；
> 可选字段显式写成 `null` 等同于省略。

段落对象：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `text` | string | 段落文本（可为空） |
| `style` | string | Word 样式名，如 `Heading 1`、`Quote`；不存在时回退普通段落 |
| `bold` / `italic` | bool | 粗体 / 斜体 |
| `size` | number | 字号（磅，1–200） |
| `align` | string | `left` / `center` / `right` / `justify` |
| `color` | string | 6 位十六进制颜色，如 `C00000` |
| `bullet` | bool | 渲染为项目符号（`• ` + 悬挂缩进） |

表格对象：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `headers` | array | 表头（可选）；存在时第一行加粗 |
| `rows` | array[array] | 数据行，元素会转成字符串 |
| `style` | string | 表格样式，默认 `Table Grid` |
| `widths` | array[number] | 每列宽度（厘米） |
| `headerBold` | bool | 表头是否加粗，默认 true |

`blocks` 元素：`{"type":"title"|"heading"|"paragraph"|"bullets"|"table"|"pageBreak", ...}`，
其余字段与上表同名；`bullets` 使用 `items: [string | {text, level:0-2}]`。

### xlsx plan

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `sheets` | array | 工作表数组，至少一个；默认生成 `Sheet1` |
| `sheets[].name` | string | 工作表名（≤31 字符，不能含 `[ ] : * ? / \`） |
| `sheets[].rows` | array[array] | 从 A1 开始写入；字符串以 `=` 开头自动当公式 |
| `sheets[].formulas` | object | `{"C4": "=SUM(B2:B3)"}`，在 rows 之后写入 |
| `sheets[].widths` | object | 列宽：`{"A": 14, "B": 18}`（0.1–255） |
| `sheets[].styles` | object | 单元格/区域样式，键为 `A1` 或 `A1:C3` |
| `sheets[].freeze` | string | 冻结窗格，如 `A2` |
| `sheets[].autofilter` | string | 自动筛选区域，如 `A1:C10` |

样式字段：`bold`、`italic`、`size`、`color`（字体色）、`fill`（背景色）、
`align`（左/中/右/两端）、`valign`（上/中/下）、`wrap`、`numberFormat`（如 `#,##0.00`）。
一个计划最多 300000 个非空单元格。

### pptx plan

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `title` / `author` / `subject` | string | 文档核心属性 |
| `font` | string | 正文字体（同时尽力设置东亚字体） |
| `slideSize` | string | `16:9`（默认）或 `4:3` |
| `cover` | object | 封面：`{title, subtitle}`；生成第一张幻灯片 |
| `slides` | array | 内容页（至少一项，除非只做封面） |
| `slides[].title` | string | 页标题 |
| `slides[].bullets` | array | 项目符号：string 或 `{text, level:0-8}` |
| `slides[].notes` | string | 演讲者备注 |
| `slides[].table` | object | `{headers, rows, widths, headerBold}`；`widths` 单位为英寸 |

同一页同时有 `bullets` 与 `table` 时，文字在上、表格在下自动排版。

## 输出 JSON 解读

所有子命令都支持 `--json`，stdout 只输出一个 UTF-8 JSON 对象（中文不转义），
进度/诊断在 stderr。失败时 stderr 输出 `{"ok":false,"code":"...","error":"...","hint":"..."}`。

### `info`

固定信封：

```json
{"format": "docx", "path": "/abs/文档.docx", "summary": { ... }}
```

| 格式 | `summary` 关键字段 |
| --- | --- |
| docx | `paragraphCount`、`nonEmptyParagraphCount`、`tableCount`、`sectionCount`、`wordCount`、`charCount`、`headings[]`、`preview[]`（前 10 段，含 `index/style/text`）、`properties`、`fonts`、`missingFonts`、`fontCheck` |
| xlsx | `sheetCount`、`sheets[]`（`name/dimensions/rows/columns/nonEmptyCells/formulaCount`）、`totalNonEmptyCells`、`totalFormulaCount` |
| pptx | `slideCount`、`slides[]`（`index/title/text/tableCount/pictureCount/hasNotes/notes`）、`slideSize`、`fonts`、`missingFonts` |
| pdf | `pageCount`、`encrypted`、`pageSize`、`metadata`（title/author/creator/producer/creationDate 等）、`pdfVersion`、`fonts` |

`wordCount` 口径：中文按字计、拉丁按词计。对 `doc/odt/xls/ods/ppt/odp`，`info` 会先转成
临时 PDF 再摘要，`summary.viaPdf` 为 true，`format` 仍是原格式。

### `convert`

`format`、`input`、`output`、`bytes`、`pageCount`、`backend`（wasm）、`missingFonts[]`、`elapsedMs`。

### `render`

`format`（png）、`input`、`outputDir`、`dpi`、`pageCount`（文档总页数）、
`pages[]`（`index/file/path/width/height/byteLength/page`，xlsx 为 `sheet/range`）、
`missingFonts[]`、`backend`、`rasterEngine`（`libreoffice` 或 `pdfium`）、`elapsedMs`。
同时把同样内容写入 `<output-dir>/manifest.json`。

### `recalc`

`format`、`input`、`output`、`bytes`、`formulaCount`、`backend`、`missingFonts[]`、`elapsedMs`。

### `create`

`format`、`output`、`bytes`、`summary`（docx 段落/表格/节/字数；xlsx 工作表/单元格/公式；
pptx 幻灯片列表）、`warnings[]`。

## 常见错误与处理

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `missingFonts: ["Arial","OpenSymbol"]` | WASM 引擎只使用可发现的字体，Arial/OpenSymbol 等未安装 | 正常现象，会自动用度量兼容字体回退；中文缺字可加 `--font-dir /usr/share/fonts` 或安装 Noto CJK/思源字体。缺失字体可能导致换行/分页偏移 |
| 退出码 2，`plan 校验失败：sheets[0].rows[2] ...` | plan 字段类型/范围不对 | 按提示修正；未知字段只给 `warnings`，不会失败 |
| 退出码 2，`--output 必须是 .pdf` | convert 输出后缀错误 | 改成 `.pdf`；若 `--output` 是已存在目录，会自动写入 `<输入名>.pdf` |
| 退出码 2，`xlsx/xls/ods 按工作表渲染` | 对表格用了 `--pages` | 改用 `--sheet "工作表名"`，可配合 `--range A1:D20` |
| 退出码 1，`LibreOffice 处理超时` | 大文件/复杂排版/冷启动 | 加 `--timeout-ms 600000`；减少页数或拆分文档。首次调用引擎冷启动约 10–30 秒属正常 |
| 退出码 1，`无法解析文档` | 文件损坏、加密、后缀与实际格式不符 | 先在 Office 中另存为正常 docx/xlsx/pptx；加密文档需先解密 |
| 退出码 3，`缺少 LibreOffice WASM 引擎` / `缺少 Python 依赖` | 运行时被裁剪 | 重装完整运行时的 `runtime/node`、`runtime/python`；不要用系统 Python 代替 `$OFFICE_KIT_PY` |
| `render` 输出页数少于预期 | 默认最多 100 页，或 `--pages` 选错 | 用 `info` 看总页数；必要时 `--max-pages` 提高上限（≤10000） |
| `create` 的 `warnings` 非空 | plan 里有拼错/未支持字段 | 检查警告中的字段路径；拼写正确后重新生成 |

退出码约定：`0` 成功，`2` 参数/plan 错误，`1` 运行时错误，`3` 缺依赖。

## 离线边界

- 引擎是随包分发的 LibreOffice **WASM**，不查找、也不依赖系统 `soffice`；不联网下载字体或模板。
- 测试脚本会把 `http_proxy/https_proxy` 指向 `127.0.0.1:9`（死端口）验证全程离线；
  所有转换、渲染、重算均通过。
- 唯二写入位置：用户指定的输出路径，以及 `$OFFICE_KIT_DATA`（默认
  `~/.local/share/office-kit`，含字体元数据缓存与临时目录）。
- 字体来自系统字体目录与 `--font-dir`；目标机没有中文字体时，中文会显示为方框，
  需预装 Noto Sans CJK / 思源黑体等字体。
- 旧版 `.doc/.xls/.ppt` 必须是 Office 97–2003 OLE 复合文档；改了后缀的 RTF/HTML 不支持。

## 与 DSH `present` 配合交付

1. 用 `convert` 产出 PDF，或用 `render` 产出 PNG；JSON 里的
   `output` / `pages[].path` 是绝对路径。
2. 建议把交付文件放在工作目录内（如 `演示文档/季度 报告.pdf`、`演示文档/汇报 预览/page-001.png`），
   便于用户打开。
3. 调用 `present` 时优先给 **1–2 个**最终文件（PDF 或首页 PNG），不要把整个预览目录塞进去；
   如果用户要看多页，先展示 `page-001.png`，其余用 Markdown 图片或路径列出。
4. 交付前可先跑 `info` 确认页数/工作表数，避免把空文档交给用户。

示例：

```text
已生成 演示文档/季度 报告.pdf（2 页）与 演示文档/汇报 预览/page-001.png。
present(files=[{path: "演示文档/季度 报告.pdf"}, {path: "演示文档/汇报 预览/page-001.png"}])
```

## 性能与限制

- `render` 默认 DPI 144（24–600），单次最多 100 页；`--pages` 支持 `1,3` 与 `1-3,5`。
- `convert/render/recalc` 默认超时 180 秒，可用 `--timeout-ms` 调整。
- `create` plan 上限 4 MB；docx 表格最多 64 列；pptx 表格最多 20 列。
- 每次引擎调用启动独立 WASM 进程，批量任务建议复用脚本循环，避免并发抢占内存。

## 自检

```sh
bash modules/office/test.sh
```

全部通过时最后一行是 `OK office`。

## WPS 文档（.wps / .wpt / .et / .ett / .dps / .dpt）

WPS Office 的自有后缀大多是 **Word/Excel/PPT 兼容的 OLE 复合文档**，本技能会先嗅探
真实容器再交给内置 LibreOffice 引擎，无需安装 WPS 或原生 LibreOffice：

| 后缀 | 实际容器 | 自动映射为 | 可用命令 |
| --- | --- | --- | --- |
| `.wps` / `.wpt` | OLE 含 `WordDocument` | `.doc` | convert / render / info |
| `.et` / `.ett` | OLE 含 `Workbook` / `Book` | `.xls` | info / convert / render / recalc |
| `.dps` / `.dpt` | OLE 含 `PowerPoint Document` | `.ppt` | convert / render / info |

```sh
# 把 WPS 文字文档转 PDF，并预览第一页
office-kit office convert --input "AI边缘计算盒子研究报告附件册.wps" --output 附件册.pdf
office-kit office render  --input "AI边缘计算盒子研究报告附件册.wps" --output-dir 预览 --pages 1 --dpi 120

# WPS 表格：读结构、转 PDF、重算公式
office-kit office info   --input "预算.et" --json
office-kit office convert --input "预算.et" --output 预算.pdf
office-kit office recalc --input "预算.et" --output 预算-重算.xlsx

# WPS 演示
office-kit office convert --input "汇报.dps" --output 汇报.pdf
```

行为说明：

- JSON 结果里 `sourceFormat` 保留原始后缀（如 `"wps"`），`format` 是实际处理的格式；
- 转换缓存放在 `$OFFICE_KIT_CACHE/office/normalized/`，同一文件重复处理不会重复复制；
- `.wps` 若是**旧版 WPS 2000 专用格式**（不是 Word 兼容容器），会提示“用 WPS 另存为
  .docx，或安装原生 LibreOffice”，不会静默产出空文档；
- 加密的 WPS 文档不支持，需先在 WPS 中解除密码。

## 命令入口（离线机必读）

本技能假设 `office-kit` 已在 `PATH` 中。若执行时报 `command not found`，改用 AppImage 绝对路径：

```sh
KIT="${OFFICE_KIT_BIN:-$HOME/apps/office-kit.AppImage}"
"$KIT" --version
```

后文所有 `office-kit <分组> ...` 都可以等价替换为 `"$KIT" <分组> ...`。
AppImage 需要 `chmod +x`；若提示 FUSE 不可用，加环境变量 `APPIMAGE_EXTRACT_AND_RUN=1`。
