# office-docs 第三方组件与许可证

本技能包（`skills/office-docs` + `modules/office`）不复制、不修改上游源码，只通过
随 office-kit 分发的运行时调用下列组件。版本为当前打包版本；实际分发时以
`runtime/` 内各组件自带的 LICENSE/NOTICE 为准。

## 办公引擎与运行时

| 组件 | 版本 | 许可证 | 来源 / 用途 |
| --- | --- | --- | --- |
| LibreOffice（WASM 引擎，含 Writer/Calc/Impress） | 26.8.0.3（引擎包 0.1.5） | MPL-2.0（内含 Apache-2.0 等第三方声明） | <https://www.libreoffice.org/>；文档转换、公式重算、Office 页面栅格化。许可证全文：`runtime/node/lib/node_modules/@deepseek-ai/libreoffice-kit-wasm/licenses/LICENSE` 与 `NOTICE` |
| @deepseek-ai/libreoffice-kit | 0.1.5 | MPL-2.0 | <https://github.com/deepseek-ai/dsh-libreoffice-kit>；Node API/CLI 封装、字体匹配、PDF 输出 |
| @deepseek-ai/libreoffice-kit-wasm | 0.1.5 | MPL-2.0 | 同上；Linux 下的 WASM 引擎资源 |
| Node.js | 22.23.3 | MIT | <https://nodejs.org/>；运行引擎 CLI |
| CPython | 3.12.15 | PSF-2.0 | <https://www.python.org/>；运行模块 Python 代码与办公库 |

## Python 办公与 PDF 库

| 组件 | 版本 | 许可证 | 来源 / 用途 |
| --- | --- | --- | --- |
| python-docx | 1.2.0 | MIT | <https://python-docx.readthedocs.io/>；docx 生成与结构读取 |
| openpyxl | 3.1.5 | MIT | <https://openpyxl.readthedocs.io/>；xlsx 生成、公式与缓存值读取 |
| python-pptx | 1.0.2 | MIT | <https://python-pptx.readthedocs.io/>；pptx 生成与结构读取 |
| pypdf | 7.1.1 | BSD-3-Clause | <https://pypdf.readthedocs.io/>；PDF 页数/元数据/字体名读取。已 vendor 到 `modules/office/lib/vendor/pypdf`，许可证随包保留 |
| lxml | 6.1.3 | BSD-3-Clause | <https://lxml.de/>；python-docx/python-pptx 的 XML 依赖 |
| et_xmlfile | 2.0.0 | MIT | <https://foss.heptapod.net/openpyxl/et_xmlfile>；openpyxl 的 XML 写入依赖 |
| typing_extensions | 4.16.0 | PSF-2.0 | <https://pypi.org/project/typing-extensions/>；python-docx/pypdf 的类型兼容层 |
| Pillow | 13.0.0 | MIT-CMU（HPND） | <https://python-pillow.org/>；自测脚本校验 PNG 尺寸/完整性 |

> 运行时中的 PyMuPDF 由 PDF/OCR 模块使用；**office 模块不使用 PyMuPDF**，以避免将
> AGPL-3.0 组件耦合进本模块的分发链路。`modules/pdf`、`modules/ocr` 的许可见各自
> `LICENSES.md`。

## Node 依赖（随 libreoffice-kit 分发）

| 组件 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| fontkit | 2.0.4 | MIT | 字体元数据/字形覆盖匹配 |
| fflate | 0.8.2 | MIT | PNG/zlib 压缩 |
| koffi | 3.1.1 | MIT | 原生 FFI（非 Linux WASM 路径使用） |
| saxes | 6.0.0 | ISC | XML 解析 |
| restructure | 3.0.2 | MIT | 二进制结构读取 |
| unicode-properties | 1.4.1 | MIT | 字符属性 |
| brotli | 1.3.3 | MIT | 压缩 |
| pako | 0.2.9 | MIT | zlib |
| tiny-inflate | 1.0.3 | MIT | 解压 |
| base64-js | 1.5.1 | MIT | Base64 |
| clone | 2.1.2 | MIT | 对象克隆 |
| dfa | 1.2.0 | MIT | 状态机 |
| fast-deep-equal | 3.1.3 | MIT | 深比较 |
| xmlchars | 2.2.0 | MIT | XML 字符集 |
| @swc/helpers | 0.5.24 | Apache-2.0 | 编译辅助运行时 |

LibreOffice 引擎包内还包含 Apache OpenOffice、Apache Lucene、Oracle、IBM 等历史
第三方声明，详见 `runtime/node/lib/node_modules/@deepseek-ai/libreoffice-kit-wasm/licenses/NOTICE`
及同目录的 `LICENSE`。DeepSeek 自有的字体数据处理部分（`DeepSeek-Harness-MIT.txt`）
为 MIT。

## 字体

office 模块**不分发字体**。转换/渲染时读取目标机系统字体目录；`--font-dir` 只追加
只读搜索路径。中文字体（Noto Sans CJK、思源黑体、文泉驿等）由其系统包按各自许可证
（常见为 SIL OFL-1.1 或 Apache-2.0）提供，随系统分发，不改变其许可。

## 合规提示

- **MPL-2.0**（LibreOffice、libreoffice-kit）：分发二进制时需保留许可证与源码获取
  方式；office-kit 的 `runtime/` 已保留 `licenses/`、`sources/` 与 `prebuilds.json`，
  分发 AppImage 时请勿裁剪这些文件。
- **Apache-2.0 / MIT / BSD / ISC**：保留版权与许可声明即可；本文件与运行时内的
  LICENSE/NOTICE 构成声明集合。
- **pypdf（BSD-3-Clause）**：`modules/office/lib/vendor/pypdf` 内保留其
  `LICENSE`/`dist-info`；若单独抽取该目录再分发，请一并保留。
- 若把本模块与 AGPL 组件（如 PyMuPDF）打包进同一分发物，请自行评估 AGPL 义务；
  office 模块本身不导入 PyMuPDF。

## 版本核对

```sh
runtime/node/bin/node --version
runtime/python/bin/python3 -V
runtime/python/bin/python3 -c "import docx, openpyxl, pptx, pypdf; print('ok')"
cat runtime/node/lib/node_modules/@deepseek-ai/libreoffice-kit/package.json | grep version
```
