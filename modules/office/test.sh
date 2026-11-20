#!/bin/bash
# office 模块自检：用 python 库生成素材 → create / convert / render / info / recalc 全链路。
# 成功输出 OK office；任何失败非 0 退出。
set -uo pipefail

_self="$(readlink -f "$0" 2>/dev/null || echo "$0")"
MODULE_DIR="$(cd "$(dirname "$_self")" && pwd)"
KIT_DIR="$(cd "${MODULE_DIR}/../.." && pwd)"

PY="${OFFICE_KIT_PY:-${KIT_DIR}/runtime/python/bin/python3}"
OFFICE="${MODULE_DIR}/bin/office"
TMP="${KIT_DIR}/.tmp/office-test.$$"
OUT="${TMP}/输出 目录"
FIX="${TMP}/fixtures"

case "${TMP}" in
  "${KIT_DIR}"/.tmp/office-test.*) ;;
  *) echo "拒绝清理非 .tmp 路径: ${TMP}" >&2; exit 1 ;;
esac

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

section() {
  echo
  echo "== $*"
}

assert_file() {
  [ -e "$1" ] || fail "输出不存在: $1"
  [ -s "$1" ] || fail "输出为空: $1"
}

assert_json() {
  local file="$1" expr="$2" desc="$3"
  [ -f "${file}" ] || fail "JSON 文件不存在: ${file}"
  "${PY}" - "${file}" "${expr}" "${desc}" <<'PY' || fail "JSON 断言失败: ${desc}"
import json
import sys

path, expr, desc = sys.argv[1:4]
try:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
except Exception as exc:  # noqa: BLE001
    raise SystemExit(f"无法解析 JSON {path}: {exc}")
env = {
    "__builtins__": {},
    "d": data,
    "len": len,
    "all": all,
    "any": any,
    "isinstance": isinstance,
    "str": str,
    "int": int,
    "float": float,
    "list": list,
    "dict": dict,
}
if not eval(expr, env, env):  # noqa: S307 - 测试脚本内部使用
    print(f"{desc}: 断言为假: {expr}", file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False)[:1200], file=sys.stderr)
    raise SystemExit(1)
print(f"  ok - {desc}")
PY
}

assert_png() {
  local file="$1"
  assert_file "${file}"
  "${PY}" - "${file}" <<'PY' || fail "PNG 校验失败: ${file}"
import sys
from PIL import Image

path = sys.argv[1]
with Image.open(path) as image:
    image.verify()
with Image.open(path) as image:
    width, height = image.size
    mode = image.mode
assert width > 0 and height > 0, (width, height)
print(f"  ok - PNG {path.rsplit('/', 1)[-1]} {width}x{height} {mode}")
PY
}

run_expect_ok() {
  local out="$1" err="$2"
  shift 2
  if ! "$@" >"${out}" 2>"${err}"; then
    echo "--- 命令失败: $* ---" >&2
    tail -n 40 "${err}" >&2
    fail "命令退出码非 0"
  fi
}

run_expect_code() {
  local expected="$1" out="$2" err="$3"
  shift 3
  "$@" >"${out}" 2>"${err}"
  local actual=$?
  if [ "${actual}" -ne "${expected}" ]; then
    echo "--- 命令: $* ---" >&2
    tail -n 40 "${err}" >&2
    fail "期望退出码 ${expected}，实际 ${actual}"
  fi
}

section "0. 环境与离线约束"
[ -x "${PY}" ] || fail "缺少 Python: ${PY}"
[ -x "${OFFICE}" ] || fail "缺少模块入口: ${OFFICE}"
rm -rf "${TMP}"
mkdir -p "${TMP}" "${OUT}" "${FIX}"
export OFFICE_KIT_DATA="${TMP}/data"
export OFFICE_KIT_CACHE="${TMP}/data/cache"
export OFFICE_KIT_LOGS="${TMP}/data/logs"
mkdir -p "${OFFICE_KIT_DATA}" "${OFFICE_KIT_CACHE}" "${OFFICE_KIT_LOGS}"
# 死代理：任何联网尝试都会立即失败，证明引擎全程离线可用。
export http_proxy="http://127.0.0.1:9"
export https_proxy="http://127.0.0.1:9"
export HTTP_PROXY="http://127.0.0.1:9"
export HTTPS_PROXY="http://127.0.0.1:9"
export ALL_PROXY="http://127.0.0.1:9"
export all_proxy="http://127.0.0.1:9"
export NO_PROXY=""
export no_proxy=""
echo "  数据目录: ${OFFICE_KIT_DATA}"

section "1. 帮助与版本"
run_expect_ok "${TMP}/help.out" "${TMP}/help.err" "${OFFICE}" --help
grep -q "convert" "${TMP}/help.out" || fail "--help 缺少 convert 说明"
run_expect_ok "${TMP}/version.out" "${TMP}/version.err" "${OFFICE}" --version
grep -q "office-kit office" "${TMP}/version.out" || fail "--version 输出异常"
run_expect_ok "${TMP}/convert-help.out" "${TMP}/convert-help.err" "${OFFICE}" convert --help
grep -q -- "--output" "${TMP}/convert-help.out" || fail "convert --help 缺少 --output"
if [ -x "${KIT_DIR}/bin/office-kit" ]; then
  run_expect_ok "${TMP}/dispatch.out" "${TMP}/dispatch.err" "${KIT_DIR}/bin/office-kit" office --help
  grep -q "render" "${TMP}/dispatch.out" || fail "office-kit 分发 --help 异常"
fi
echo "  ok - help / version / 分发"

section "2. 用 Python 生成测试素材"
run_expect_ok "${TMP}/fixtures.out" "${TMP}/fixtures.err" \
  "${PY}" "${MODULE_DIR}/testdata/make_fixtures.py" "${FIX}"
assert_file "${FIX}/自测 文档.docx"
assert_file "${FIX}/预算 表.xlsx"
assert_file "${FIX}/汇报 演示.pptx"
echo "  ok - python-docx / openpyxl / python-pptx 素材"

section "3. create：plan 生成三种文档（中文 + 空格路径）"
run_expect_ok "${TMP}/create-docx.json" "${TMP}/create-docx.err" \
  "${OFFICE}" create --type docx --output "${OUT}/季度 报告.docx" \
  --plan "${MODULE_DIR}/testdata/plans/docx.json" --json
assert_file "${OUT}/季度 报告.docx"
assert_json "${TMP}/create-docx.json" \
  'd["format"] == "docx" and d["bytes"] > 0 and d["summary"]["paragraphCount"] > 0 and d["summary"]["tableCount"] >= 1' \
  "create docx 摘要"

run_expect_ok "${TMP}/create-xlsx.json" "${TMP}/create-xlsx.err" \
  "${OFFICE}" create --type xlsx --output "${OUT}/预算 表.xlsx" \
  --plan "${MODULE_DIR}/testdata/plans/xlsx.json" --json
assert_file "${OUT}/预算 表.xlsx"
assert_json "${TMP}/create-xlsx.json" \
  'd["format"] == "xlsx" and d["summary"]["sheetCount"] == 2 and d["summary"]["totalFormulaCount"] >= 2' \
  "create xlsx 多工作表与公式"

run_expect_ok "${TMP}/create-pptx.json" "${TMP}/create-pptx.err" \
  "${OFFICE}" create --type pptx --output "${OUT}/汇报 演示.pptx" \
  --plan "${MODULE_DIR}/testdata/plans/pptx.json" --json
assert_file "${OUT}/汇报 演示.pptx"
assert_json "${TMP}/create-pptx.json" \
  'd["format"] == "pptx" and d["summary"]["slideCount"] >= 3' \
  "create pptx 幻灯片"

printf '%s' '{"title":"stdin 文档","blocks":[{"type":"heading","level":1,"text":"从标准输入生成"},{"type":"paragraph","text":"blocks 顺序渲染测试。"},{"type":"bullets","items":["甲","乙"]},{"type":"table","headers":["A","B"],"rows":[["1","2"]]},{"type":"pageBreak"},{"type":"paragraph","text":"第二页"}]}' \
  | "${OFFICE}" create --type docx --output "${TMP}/stdin 文档.docx" --plan - --json \
    >"${TMP}/create-stdin.json" 2>"${TMP}/create-stdin.err" \
  || { tail -n 20 "${TMP}/create-stdin.err" >&2; fail "stdin plan 生成失败"; }
assert_json "${TMP}/create-stdin.json" \
  'd["summary"]["tableCount"] == 1 and d["summary"]["paragraphCount"] >= 5' \
  "create --plan -（blocks 顺序）"

# 缺省值用例：只给 headers/rows，不写 widths/style/headerBold；可选字段传 null 也应正常。
printf '%s' '{"title":"最小表格","paragraphs":["..."],"tables":[{"headers":["项目","金额"],"rows":[["办公",123.45]]}]}' \
  | "${OFFICE}" create --type docx --output "${TMP}/最小 表格.docx" --plan - --json \
    >"${TMP}/create-min-docx.json" 2>"${TMP}/create-min-docx.err" \
  || { tail -n 20 "${TMP}/create-min-docx.err" >&2; fail "docx headers-only 表格生成失败"; }
assert_json "${TMP}/create-min-docx.json" \
  'd["summary"]["tableCount"] == 1 and d["summary"]["paragraphCount"] >= 1' \
  "create docx 缺省 widths/style"

printf '%s' '{"sheets":[{"name":"默认","rows":[["A"]]}]}' \
  | "${OFFICE}" create --type xlsx --output "${TMP}/最小 表.xlsx" --plan - --json \
    >"${TMP}/create-min-xlsx.json" 2>"${TMP}/create-min-xlsx.err" \
  || { tail -n 20 "${TMP}/create-min-xlsx.err" >&2; fail "xlsx 缺省 plan 生成失败"; }
assert_json "${TMP}/create-min-xlsx.json" \
  'd["summary"]["sheetCount"] == 1 and d["summary"]["totalNonEmptyCells"] == 1' \
  "create xlsx 缺省 formulas/widths/styles"

printf '%s' '{"slides":[{"title":"默认页","bullets":["唯一"]}]}' \
  | "${OFFICE}" create --type pptx --output "${TMP}/最小 演示.pptx" --plan - --json \
    >"${TMP}/create-min-pptx.json" 2>"${TMP}/create-min-pptx.err" \
  || { tail -n 20 "${TMP}/create-min-pptx.err" >&2; fail "pptx 缺省 plan 生成失败"; }
assert_json "${TMP}/create-min-pptx.json" \
  'd["summary"]["slideCount"] == 1 and d["summary"]["slides"][0]["bulletCount"] == 1' \
  "create pptx 缺省 cover/notes/table"

printf '%s' '{"title":null,"paragraphs":[{"text":"null 字段","bold":null}],"tables":[{"headers":["A"],"rows":[["1"]],"widths":null,"style":null}]}' \
  | "${OFFICE}" create --type docx --output "${TMP}/null 字段.docx" --plan - --json \
    >"${TMP}/create-null-docx.json" 2>"${TMP}/create-null-docx.err" \
  || { tail -n 20 "${TMP}/create-null-docx.err" >&2; fail "可选字段为 null 时生成失败"; }
assert_json "${TMP}/create-null-docx.json" \
  'd["summary"]["tableCount"] == 1 and len(d["warnings"]) == 0' \
  "create 可选字段 null 容错"

echo "  ok - create 三种类型 + stdin + 缺省值"

section "4. info：docx / xlsx / pptx / pdf"
run_expect_ok "${TMP}/info-docx.json" "${TMP}/info-docx.err" \
  "${OFFICE}" info --input "${OUT}/季度 报告.docx" --json
assert_json "${TMP}/info-docx.json" \
  'd["format"] == "docx" and d["path"].endswith(".docx") and d["summary"]["paragraphCount"] > 0 and len(d["summary"]["preview"]) > 0 and isinstance(d["summary"]["missingFonts"], list)' \
  "info docx 字段"

run_expect_ok "${TMP}/info-xlsx.json" "${TMP}/info-xlsx.err" \
  "${OFFICE}" info --input "${OUT}/预算 表.xlsx" --json
assert_json "${TMP}/info-xlsx.json" \
  'd["format"] == "xlsx" and d["summary"]["sheetCount"] == 2 and d["summary"]["totalFormulaCount"] >= 2 and d["summary"]["sheets"][0]["dimensions"].startswith("A1:")' \
  "info xlsx 字段"

run_expect_ok "${TMP}/info-pptx.json" "${TMP}/info-pptx.err" \
  "${OFFICE}" info --input "${OUT}/汇报 演示.pptx" --json
assert_json "${TMP}/info-pptx.json" \
  'd["format"] == "pptx" and d["summary"]["slideCount"] >= 3 and len(d["summary"]["slides"]) == d["summary"]["slideCount"] and d["summary"]["slides"][0]["text"] != ""' \
  "info pptx 字段"

section "5. convert：docx → PDF"
run_expect_ok "${TMP}/convert.json" "${TMP}/convert.err" \
  "${OFFICE}" convert --input "${OUT}/季度 报告.docx" --output "${OUT}/季度 报告.pdf" \
  --json --timeout-ms 600000
assert_file "${OUT}/季度 报告.pdf"
[ "$(head -c 5 "${OUT}/季度 报告.pdf")" = "%PDF-" ] || fail "输出不是 PDF"
assert_json "${TMP}/convert.json" \
  'd["format"] == "pdf" and d["bytes"] > 0 and d["pageCount"] >= 1 and isinstance(d["missingFonts"], list) and d["output"].endswith(".pdf")' \
  "convert 结果字段"

run_expect_ok "${TMP}/info-pdf.json" "${TMP}/info-pdf.err" \
  "${OFFICE}" info --input "${OUT}/季度 报告.pdf" --json
assert_json "${TMP}/info-pdf.json" \
  'd["format"] == "pdf" and d["summary"]["pageCount"] >= 1 and isinstance(d["summary"]["metadata"], dict) and d["summary"]["pageSize"]["width"] > 0' \
  "info pdf 页数与元数据"

section "6. render：docx 区间页 + PDF 渲染"
run_expect_ok "${TMP}/render-docx.json" "${TMP}/render-docx.err" \
  "${OFFICE}" render --input "${FIX}/自测 文档.docx" --output-dir "${OUT}/文档 预览" \
  --pages 1-2 --dpi 96 --json
assert_json "${TMP}/render-docx.json" \
  'd["format"] == "png" and len(d["pages"]) == 2 and all(p["width"] > 0 and p["height"] > 0 and p["byteLength"] > 0 for p in d["pages"]) and isinstance(d["missingFonts"], list)' \
  "render docx 两页 JSON"
assert_file "${OUT}/文档 预览/page-001.png"
assert_file "${OUT}/文档 预览/page-002.png"
assert_file "${OUT}/文档 预览/manifest.json"
assert_png "${OUT}/文档 预览/page-001.png"
assert_png "${OUT}/文档 预览/page-002.png"

run_expect_ok "${TMP}/render-pdf.json" "${TMP}/render-pdf.err" \
  "${OFFICE}" render --input "${OUT}/季度 报告.pdf" --output-dir "${OUT}/PDF 预览" \
  --pages 1 --dpi 96 --json
assert_json "${TMP}/render-pdf.json" \
  'len(d["pages"]) == 1 and d["pages"][0]["width"] > 0 and d["rasterEngine"] == "pdfium"' \
  "render pdf（pdfium）"
assert_png "${OUT}/PDF 预览/page-001.png"

section "7. recalc：公式缓存刷新"
run_expect_ok "${TMP}/recalc.json" "${TMP}/recalc.err" \
  "${OFFICE}" recalc --input "${OUT}/预算 表.xlsx" --output "${OUT}/重算 结果.xlsx" --json
assert_file "${OUT}/重算 结果.xlsx"
assert_json "${TMP}/recalc.json" \
  'd["format"] == "xlsx" and d["bytes"] > 0 and d["formulaCount"] >= 2 and d["output"].endswith(".xlsx")' \
  "recalc 结果字段"
"${PY}" - "${OUT}/重算 结果.xlsx" <<'PY' || fail "recalc 未写入缓存值或公式丢失"
import sys

import openpyxl

path = sys.argv[1]
formulas = openpyxl.load_workbook(path, data_only=False)["销售汇总"]
values = openpyxl.load_workbook(path, data_only=True)["销售汇总"]
assert formulas["B4"].value == "=SUM(B2:B3)", formulas["B4"].value
assert values["B4"].value == 2700, values["B4"].value
assert formulas["C4"].value == "=SUM(B2:B3)/100", formulas["C4"].value
assert values["C4"].value == 27, values["C4"].value
print("  ok - 公式保留且缓存值正确（2700 / 27）")
PY

section "8. 错误码与 plan 校验"
run_expect_code 1 "${TMP}/err-missing.out" "${TMP}/err-missing.err" \
  "${OFFICE}" convert --input "${TMP}/不存在.docx" --output "${OUT}/不存在.pdf" --json
grep -q '"code": "runtime"' "${TMP}/err-missing.err" || fail "缺输入文件未返回 runtime 错误码"

printf '{"headings":[{"level":99,"text":"越界"}]}' > "${TMP}/bad-plan.json"
run_expect_code 2 "${TMP}/err-plan.out" "${TMP}/err-plan.err" \
  "${OFFICE}" create --type docx --output "${OUT}/bad.docx" --plan "${TMP}/bad-plan.json" --json
grep -q '"code": "usage"' "${TMP}/err-plan.err" || fail "坏 plan 未返回 usage 错误码"

run_expect_code 2 "${TMP}/err-pages.out" "${TMP}/err-pages.err" \
  "${OFFICE}" render --input "${FIX}/自测 文档.docx" --output-dir "${TMP}/bad-pages" --pages 0 --json
grep -q '"code": "usage"' "${TMP}/err-pages.err" || fail "非法页码未返回 usage 错误码"

printf '%s' '{"title":"警告测试","unknownField":1}' \
  | "${OFFICE}" create --type docx --output "${TMP}/warning.docx" --plan - --json \
    >"${TMP}/warning.json" 2>"${TMP}/warning.err" \
  || fail "带未知字段的 plan 不应失败"
assert_json "${TMP}/warning.json" \
  'len(d["warnings"]) >= 1 and d["summary"]["paragraphCount"] >= 1' \
  "未知字段给出 warnings"

section "9. WPS 格式（.wps / .et）"
# .et：用 xlwt 造一个真实的 Excel 97 复合文档，再改名成 .et（WPS 表格）
"${PY}" - "${TMP}" <<'PYX' || fail "生成 .et 测试素材失败"
import sys
import xlwt

tmp = sys.argv[1]
wb = xlwt.Workbook()
ws = wb.add_sheet("预算")
rows = [["项目", "数量", "单价", "金额"], ["办公", 2, 123.45, None], ["文档", 1, 10, None]]
for r, row in enumerate(rows):
    for c, value in enumerate(row):
        if value is not None:
            ws.write(r, c, value)
ws.write(1, 3, xlwt.Formula("B2*C2"))
ws.write(2, 3, xlwt.Formula("B3*C3"))
wb.save(tmp + "/wps-source.xls")
PYX
cp "${TMP}/wps-source.xls" "${TMP}/示例 表格.et"

"${OFFICE}" info --input "${TMP}/示例 表格.et" --json >"${TMP}/et-info.json" 2>"${TMP}/et-info.err" \
  || fail "et info 失败（见 ${TMP}/et-info.err）"
assert_json "${TMP}/et-info.json" \
  'd["sourceFormat"] == "et" and d["format"] == "xls"' \
  "et 被识别为 WPS 表格"

"${OFFICE}" convert --input "${TMP}/示例 表格.et" --output "${OUT}/et 转.pdf" --json >"${TMP}/et-pdf.json" 2>"${TMP}/et-pdf.err" \
  || fail "et convert 失败（见 ${TMP}/et-pdf.err）"
assert_file "${OUT}/et 转.pdf"
assert_json "${TMP}/et-pdf.json" 'd["sourceFormat"] == "et" and d["pageCount"] >= 1' "et 转 PDF"

"${OFFICE}" recalc --input "${TMP}/示例 表格.et" --output "${TMP}/et-recalc.xlsx" --json >"${TMP}/et-recalc.json" 2>"${TMP}/et-recalc.err" \
  || fail "et recalc 失败（见 ${TMP}/et-recalc.err）"
assert_json "${TMP}/et-recalc.json" 'd["formulaCount"] == 2' "et 公式重算（2 个公式）"

# .wps：需要真实 WPS 文档（可选，通过环境变量提供）
if [ -n "${OFFICE_KIT_WPS_FIXTURE:-}" ] && [ -f "${OFFICE_KIT_WPS_FIXTURE}" ]; then
  cp "${OFFICE_KIT_WPS_FIXTURE}" "${TMP}/示例 文档.wps"
  "${OFFICE}" info --input "${TMP}/示例 文档.wps" --json >"${TMP}/wps-info.json" 2>"${TMP}/wps-info.err" \
    || fail "wps info 失败（见 ${TMP}/wps-info.err）"
  assert_json "${TMP}/wps-info.json" 'd["sourceFormat"] == "wps"' "wps 被识别"
  "${OFFICE}" convert --input "${TMP}/示例 文档.wps" --output "${OUT}/wps 转.pdf" --json >"${TMP}/wps-pdf.json" 2>"${TMP}/wps-pdf.err" \
    || fail "wps convert 失败（见 ${TMP}/wps-pdf.err）"
  assert_file "${OUT}/wps 转.pdf"
  "${OFFICE}" render --input "${TMP}/示例 文档.wps" --output-dir "${TMP}/wps-png" --pages 1 --dpi 72 --json >"${TMP}/wps-png.json" 2>"${TMP}/wps-png.err" \
    || fail "wps render 失败（见 ${TMP}/wps-png.err）"
  ls "${TMP}/wps-png"/*.png >/dev/null 2>&1 || fail "wps 未渲染出 PNG"
  echo "  ok - .wps 转换/渲染/摘要"
else
  echo "  SKIP - .wps 实文档用例（设置 OFFICE_KIT_WPS_FIXTURE=/path/x.wps 可启用）"
fi

section "10. 结果清单"
echo "  输出目录: ${OUT}"
ls -1 "${OUT}" | sed 's/^/    /'
echo
echo "OK office"
