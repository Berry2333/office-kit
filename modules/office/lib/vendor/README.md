# vendor — office 模块私有 Python 依赖

本目录存放 office 模块自己的小型纯 Python 依赖，不修改 `runtime/python` 的
site-packages，也不影响其他模块。

## pypdf 7.1.1

- 来源：PyPI `pypdf==7.1.1`（BSD-3-Clause）
- 安装方式（构建期）：
  ```sh
  runtime/python/bin/python3 -m pip install --no-deps --no-cache-dir \
    --target modules/office/lib/vendor pypdf==7.1.1
  ```
- 用途：`info` 读取 PDF 页数、元数据、页面尺寸与字体名；不用于渲染（PDF 渲染走
  LibreOffice WASM 内置的 pdfium）。
- 许可证：`pypdf-7.1.1.dist-info/licenses/LICENSE`；说明见
  `skills/office-docs/LICENSES.md`。

`modules/office/bin/office` 会把本目录加入 `PYTHONPATH` 的最前面，因此运行时不依赖
系统中是否安装 pypdf。
