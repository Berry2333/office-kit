# office 模块测试素材

- `make_fixtures.py`：用 python-docx / openpyxl / python-pptx 生成小型 docx/xlsx/pptx 样本，
  不依赖任何仓库外素材。
- `fixtures/`：上述生成器的示例产物（可随时重新生成，二进制很小）：
  - `自测 文档.docx`：两页、标题、表格、中文，用于 `--pages 1-2` 区间渲染；
  - `预算 表.xlsx`：两个工作表、`SUM`/`AVERAGE` 公式，用于 `recalc` 缓存值断言；
  - `汇报 演示.pptx`：封面 + 内容页 + 表格页，用于结构摘要与渲染。
- `plans/`：`create` 子命令的示例 plan（docx/xlsx/pptx）。

重新生成：

```sh
runtime/python/bin/python3 modules/office/testdata/make_fixtures.py modules/office/testdata/fixtures
```

`modules/office/test.sh` 每次会把自己的素材生成到独立的
`.tmp/office-test.<pid>/fixtures/`，避免并发测试互相覆盖，因此不依赖本目录的旧文件。
