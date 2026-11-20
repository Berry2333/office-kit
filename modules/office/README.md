# modules/office — Word / Excel / PowerPoint 能力模块

`office-kit office` 的模块实现，提供五个子命令：

| 子命令 | 作用 |
| --- | --- |
| `convert` | doc/docx/odt、xls/xlsx/ods、ppt/pptx/odp → PDF |
| `render` | 文档逐页渲染为 PNG（Office 用 LibreOffice，PDF 用 pdfium），输出 `manifest.json` |
| `recalc` | 刷新 xls/xlsx/ods 的公式缓存（保留公式） |
| `info` | docx/xlsx/pptx/pdf 结构摘要；其余 Office 格式先转 PDF 再摘要 |
| `create` | 按 JSON plan 生成 docx / xlsx / pptx |

运行时**完全离线**：Office 引擎为随包分发的 LibreOffice WASM（`runtime/node`），
文档生成/解析使用 `runtime/python` + python-docx / openpyxl / python-pptx，PDF 摘要使用
模块自带的 `pypdf`。不依赖系统 `soffice`、Java、Node、Python 或网络。

## 文件布局

```
modules/office/
  bin/office                 # bash 入口：解析 OFFICE_KIT_* → 调用 lib/office_cli.py
  lib/office_cli.py          # 参数解析、convert/render/recalc/info/create 调度
  lib/office_common.py       # 路径/错误模型、WASM 引擎调用、字体探测
  lib/office_create.py       # plan 校验与 docx/xlsx/pptx 生成
  lib/office_info.py         # docx/xlsx/pptx/pdf 摘要
  lib/vendor/pypdf/          # 纯 Python PDF 解析（BSD-3-Clause，模块私有）
  testdata/make_fixtures.py  # 自测素材生成器（不依赖外部样本）
  testdata/fixtures/         # 生成器产出的 docx/xlsx/pptx 小样本
  testdata/plans/*.json      # create 示例 plan
  test.sh                    # 全链路自检（成功打印 OK office）
  README.md
```

## 路径解析与环境变量

模块入口优先使用契约变量；未导出时按脚本相对路径回退，因此可以直接执行
`modules/office/bin/office`：

```bash
RUNTIME="${OFFICE_KIT_RUNTIME:-$(cd "$(dirname "$0")/../../runtime" && pwd)}"
```

| 变量 | 用途 |
| --- | --- |
| `OFFICE_KIT_ROOT` | 仓库/AppDir 根目录 |
| `OFFICE_KIT_RUNTIME` | `runtime/` |
| `OFFICE_KIT_DATA` | 可写数据目录，默认 `${XDG_DATA_HOME:-$HOME/.local/share}/office-kit` |
| `OFFICE_KIT_CACHE` | 引擎字体元数据缓存（子进程 `XDG_CACHE_HOME` 指到这里） |
| `OFFICE_KIT_LOGS` | 日志目录（预留给后续诊断） |
| `OFFICE_KIT_PY` | `runtime/python/bin/python3` |
| `OFFICE_KIT_PY_SITE` | 运行时 site-packages |
| `OFFICE_KIT_NODE` | `runtime/node/bin/node` |
| `OFFICE_KIT_NODE_MODULES` | `runtime/node/lib/node_modules` |
| `OFFICE_KIT_LANG` | 默认 `zh_CN` |

模块只向用户输出路径与 `$OFFICE_KIT_DATA`（缓存/临时目录）写入，不会修改 `runtime/` 和系统目录。

## 用法

```sh
office-kit office --help
office-kit office convert --input 报告.docx --output 报告.pdf --json
office-kit office render  --input 报告.docx --output-dir 预览 --pages 1-3 --dpi 144 --json
office-kit office recalc  --input 预算.xlsx --output 预算-重算.xlsx --json
office-kit office info    --input 汇报.pptx --json
office-kit office create  --type docx --output 报告.docx --plan plan.json --json
```

每个子命令都支持 `--json`（stdout 单个 UTF-8 JSON 对象，中文不转义），诊断写 stderr。
`convert/render/recalc` 另支持 `--timeout-ms`（默认 180000）与可重复的 `--font-dir DIR`；
`render` 支持 `--pages`（`1,3` / `1-3,5` / 省略=全部）、`--dpi`（24–600）、`--max-pages`，
xlsx 渲染用 `--sheet` + `--range` 而不是 `--pages`。

plan schema、JSON 字段、错误处理与交付建议见
[`skills/office-docs/SKILL.md`](../../skills/office-docs/SKILL.md)。

## 实现要点

- **入口（bash）**：解析根目录/运行时，校验 Python 与引擎入口；设置 `PYTHONPATH`
  （模块 `lib/vendor` 优先）和 UTF-8 环境；`exec` Python CLI，不改变用户参数。
- **引擎调用**：`node .../libreoffice-kit/lib/cli.js <command> ...`，其 stdout 始终是
  JSON。模块解析该 JSON，把引擎 stderr 的最后 20 行作为诊断保留；引擎错误码
  （`timeout`/`unavailable`/`invalid-document` 等）映射为契约退出码 1/3，并给出修复提示。
- **原子输出**：先写同文件系统下的临时目录/临时文件，成功后 `os.replace` 覆盖目标；
  失败清理临时文件，不会留下半成品。引擎输出权限为 0600，交付时放宽到 0644。
- **render 后处理**：把引擎的 `page-0001.png` 等稳定重命名为 `page-001.png`，清理旧页，
  重写 `manifest.json`（含 `pages[]`、`missingFonts[]`、后端、DPI 等），便于模型直接消费。
- **字体**：`info` 用 `fc-list` 对比 docx 样式/run 实际引用的字体、pptx 主题字体，
  给出 `missingFonts`（启发式）；`convert/render/recalc` 透传引擎实际报告的
  `missingFonts`。`--font-dir` 原样传给引擎。
- **plan 校验**：严格检查类型/范围/工作表名/单元格引用，错误信息带 JSON 路径；未知字段
  只记入 `warnings[]`，不中断生成；`--plan -` 从 stdin 读取，上限 4 MB。
- **xlsx 公式**：plan 中 `=` 开头的字符串与 `formulas` 映射都写成公式；`recalc` 由
  LibreOffice 重算并写回缓存值，openpyxl 的 `data_only=True` 可读取结果。
- **PDF 摘要**：使用模块内 vendor 的 pypdf（BSD-3），不依赖 PyMuPDF，避免把 AGPL
  组件耦合进 office 模块的分发链路。

## 测试

```sh
bash modules/office/test.sh
```

脚本会：

1. 用 `runtime/python` 的 python-docx / openpyxl / python-pptx 生成 docx/xlsx/pptx 素材
   （每次写入独立的 `.tmp/office-test.<pid>/fixtures/`，避免并发互踩；仓库内的
   `testdata/fixtures/` 是同一生成器的示例产物）；
2. 跑 `create`（三种类型 + stdin/blocks）、`info`（docx/xlsx/pptx/pdf）、`convert`、
   `render`（docx 区间页 + PDF/pdfium）、`recalc`（公式保留 + 缓存值断言）；
3. 断言输出文件、PDF 魔数、PNG 尺寸、JSON 字段、错误码；
4. 把 `http_proxy/https_proxy/ALL_PROXY` 指向 `127.0.0.1:9` 验证不联网；
5. 全部通过后打印 `OK office`。

临时文件在 `.tmp/office-test.<pid>/`，每次运行使用独立目录，可并发执行；测试数据由
脚本生成，不依赖仓库外样本。重新生成素材可单独执行：

```sh
runtime/python/bin/python3 modules/office/testdata/make_fixtures.py modules/office/testdata/fixtures
```

## 已知限制

- WASM 引擎的排版保真度取决于可用字体；`Arial`、`Calibri`、`OpenSymbol` 等缺失会回退，
  可能造成换行/分页与商业 Office 略有差异。中文字体缺失时会显示方框。
- 二进制 `.doc/.xls/.ppt` 必须是 Office 97–2003 OLE 文档；改后缀的 RTF/HTML 不支持。
- `render` 单次默认最多 100 页、DPI 24–600；超大文档请分页或拆分。
- `info` 对 `doc/odt/xls/ods/ppt/odp` 通过临时 PDF 间接摘要，字段是 PDF 层面的；
  扫描件 PDF 没有文本层，需配合 OCR 工具。
- 加密文档需先解密；`convert` 不提供密码参数。
- 引擎每次调用启动独立进程，首次调用（冷缓存）约 10–30 秒；批量任务建议顺序执行。

## 许可

模块自身代码由 office-kit 项目维护；第三方组件与许可证见
[`skills/office-docs/LICENSES.md`](../../skills/office-docs/LICENSES.md)。


## WPS 格式（.wps / .et / .dps）

WPS 后缀不是 LibreOffice 的过滤器名，因此模块在调用引擎前做一次「容器嗅探」：

1. `zipfile` 读 `[Content_Types].xml` → docx/xlsx/pptx；
2. OLE 魔数 + UTF-16LE 流名 → `WordDocument`=doc、`Workbook`/`Book`=xls、
   `PowerPoint Document`=ppt；
3. RTF / HTML / 纯文本按内容识别；
4. 复制/链接到 `$OFFICE_KIT_CACHE/office/normalized/` 后以正确后缀交给引擎。

无法嗅探的旧格式（WPS 2000）在系统有原生 `soffice` 时走 `convert_with_soffice` 兜底，
否则以退出码 1 给出明确提示。
