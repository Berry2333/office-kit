#!/bin/bash
# modules/ofd/test.sh — OFD 模块自检（离线，不访问网络）
#
# 覆盖：demo 生成 / info / to-pdf / to-image / to-text / to-html / merge / from-pdf
#       + 中文与空格路径 + JSON 字段 + 错误退出码
# 成功时最后打印: OK ofd
set -uo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_ROOT="$(cd "${MODULE_DIR}/../.." && pwd)"
OFD="${MODULE_DIR}/bin/ofd"
PY="${OFFICE_KIT_PY:-${KIT_ROOT}/runtime/python/bin/python3}"
TMP="${KIT_ROOT}/.tmp/ofd/test"

# 断网语义：所有 HTTP(S) 请求都应失败；测试中若真的联网会立即报连接错误
export http_proxy="http://127.0.0.1:9"
export https_proxy="http://127.0.0.1:9"
export HTTP_PROXY="http://127.0.0.1:9"
export HTTPS_PROXY="http://127.0.0.1:9"
export no_proxy=""
export NO_PROXY=""

fail() {
  printf 'FAIL ofd: %s\n' "$*" >&2
  exit 1
}

step() { printf '[ofd-test] %s\n' "$*"; }

[ -x "${OFD}" ] || fail "缺少可执行入口: ${OFD}（先执行 bash modules/ofd/build.sh）"
[ -x "${PY}" ] || fail "缺少 Python: ${PY}"
"${PY}" -c "import pymupdf" >/dev/null 2>&1 || fail "Python 缺少 pymupdf，无法校验 PDF（$PY）"

rm -rf "${TMP}"
mkdir -p "${TMP}"

# ---------------------------------------------------------------------------
step "1/10 生成中文演示 OFD（2 页，内嵌字体）"
"${OFD}" demo --output "${TMP}/演示 文档.ofd" --json > "${TMP}/demo.json" 2> "${TMP}/demo.err" \
  || { cat "${TMP}/demo.err" >&2; fail "demo 生成失败"; }
[ -s "${TMP}/演示 文档.ofd" ] || fail "演示 OFD 为空"

"${PY}" - "${TMP}/demo.json" <<'PY' || fail "demo JSON 校验失败"
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d["pages"] == 2, d
assert d["embedded"] is True, "演示字体应内嵌"
assert d["file_size"] > 1000
PY

# ---------------------------------------------------------------------------
step "2/10 info"
"${OFD}" info --input "${TMP}/演示 文档.ofd" --json > "${TMP}/info.json" 2> "${TMP}/info.err" \
  || { cat "${TMP}/info.err" >&2; fail "info 失败"; }
"${PY}" - "${TMP}/info.json" <<'PY' || fail "info JSON 校验失败"
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d["pages"] == 2, d["pages"]
assert d["version"], "缺少版本"
assert d["doc_type"] in ("OFD", "OFD-A")
assert len(d["page_sizes"]) == 2
w, h = d["page_sizes"][0]
assert 200 <= w <= 220 and 280 <= h <= 310, (w, h)
assert d["doc_id"], "缺少 DocID"
assert d["text_blocks"] > 0, "文本块数量为 0"
assert d["fonts"] and d["fonts"][0]["embedded"] is True, d["fonts"]
assert d["signatures"]["count"] == 0
assert d["encrypted"] is False
PY

# ---------------------------------------------------------------------------
step "3/10 to-pdf + PyMuPDF 校验（页数 / 中文 / 非空白渲染）"
"${OFD}" to-pdf --input "${TMP}/演示 文档.ofd" --output "${TMP}/演示 文档.pdf" --json > "${TMP}/pdf.json" 2> "${TMP}/pdf.err" \
  || { cat "${TMP}/pdf.err" >&2; fail "to-pdf 失败"; }
[ -s "${TMP}/演示 文档.pdf" ] || fail "PDF 为空"
"${PY}" - "${TMP}/演示 文档.pdf" <<'PY' || fail "PDF 校验失败（pymupdf）"
import pymupdf as fitz, sys
path = sys.argv[1]
doc = fitz.open(path)
assert doc.page_count == 2, doc.page_count
text = "".join(p.get_text() for p in doc)
for kw in ("电子发票", "价税合计", "第二页", "office-kit"):
    assert kw in text, f"PDF 文本缺少: {kw}"
pix = doc[0].get_pixmap(dpi=72)
s = pix.samples
dark = sum(1 for i in range(0, len(s), 3) if s[i] < 200 or s[i+1] < 200 or s[i+2] < 200)
assert dark > 500, f"PDF 首页渲染几乎空白（暗像素 {dark}）"
PY

# ---------------------------------------------------------------------------
step "4/10 to-image（默认 144dpi，page-001.png）"
"${OFD}" to-image --input "${TMP}/演示 文档.ofd" --output-dir "${TMP}/图片 输出" --json > "${TMP}/img.json" 2> "${TMP}/img.err" \
  || { cat "${TMP}/img.err" >&2; fail "to-image 失败"; }
for n in page-001.png page-002.png; do
  [ -s "${TMP}/图片 输出/${n}" ] || fail "缺少或空文件: ${n}"
done
"${PY}" - "${TMP}/图片 输出" "${TMP}/img.json" <<'PY' || fail "PNG 校验失败"
import json, os, struct, sys
d = json.load(open(sys.argv[2], encoding="utf-8"))
assert d["dpi"] == 144 and d["pages"] == 2, d
assert len(d["images"]) == 2
for name in ("page-001.png", "page-002.png"):
    p = os.path.join(sys.argv[1], name)
    with open(p, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", p
    w, h = struct.unpack(">II", head[16:24])
    assert w >= 1000 and h >= 1400, (name, w, h)
    assert os.path.getsize(p) > 2000, p
PY

# ---------------------------------------------------------------------------
step "5/10 to-text（逐页 + 坐标）"
"${OFD}" to-text --input "${TMP}/演示 文档.ofd" --json > "${TMP}/text.json" 2> "${TMP}/text.err" \
  || { cat "${TMP}/text.err" >&2; fail "to-text 失败"; }
"${PY}" - "${TMP}/text.json" <<'PY' || fail "to-text JSON 校验失败"
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d["page_count"] == 2, d["page_count"]
texts = []
for page in d["pages"]:
    assert len(page["size"]) == 2 and page["size"][0] > 0
    for line in page["lines"]:
        assert isinstance(line["text"], str) and line["text"]
        box = line["box"]
        assert len(box) == 4 and all(isinstance(v, (int, float)) for v in box), line
        texts.append(line["text"])
joined = "".join(texts)
for kw in ("电子发票", "价税合计", "第二页", "关键词"):
    assert kw in joined, f"缺少文本: {kw}"
assert any(l["box"][0] > 0 and l["box"][1] > 0 for p in d["pages"] for l in p["lines"])
PY

# ---------------------------------------------------------------------------
step "6/10 to-html（自包含 index.html）"
"${OFD}" to-html --input "${TMP}/演示 文档.ofd" --output "${TMP}/html 输出" --json > "${TMP}/html.json" 2> "${TMP}/html.err" \
  || { cat "${TMP}/html.err" >&2; fail "to-html 失败"; }
[ -s "${TMP}/html 输出/index.html" ] || fail "index.html 为空"
"${PY}" - "${TMP}/html 输出/index.html" <<'PY' || fail "HTML 校验失败"
import sys
s = open(sys.argv[1], encoding="utf-8").read()
assert s.count("svgItem") == 2, s.count("svgItem")
assert s.count("<svg") >= 2
assert 'lang="zh-CN"' in s
assert "<?xml" not in s and "<!DOCTYPE svg" not in s, "SVG 内嵌清理失败"
assert len(s) > 10000
PY

# ---------------------------------------------------------------------------
step "7/10 merge（2+2=4 页）"
"${OFD}" merge --input "${TMP}/演示 文档.ofd" --input "${TMP}/演示 文档.ofd" \
  --output "${TMP}/合并 结果.ofd" --json > "${TMP}/merge.json" 2> "${TMP}/merge.err" \
  || { cat "${TMP}/merge.err" >&2; fail "merge 失败"; }
"${OFD}" info --input "${TMP}/合并 结果.ofd" --json > "${TMP}/merged-info.json" \
  || fail "读取合并结果失败"
"${PY}" - "${TMP}/merge.json" "${TMP}/merged-info.json" <<'PY' || fail "merge 校验失败"
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
i = json.load(open(sys.argv[2], encoding="utf-8"))
assert m["pages"] == 4 and i["pages"] == 4, (m["pages"], i["pages"])
assert len(m["inputs"]) == 2
PY

# ---------------------------------------------------------------------------
step "8/10 from-pdf（PDF -> OFD，auto / 必要时回退图形化）"
"${OFD}" from-pdf --input "${TMP}/演示 文档.pdf" --output "${TMP}/回环.ofd" --json > "${TMP}/frompdf.json" 2> "${TMP}/frompdf.err" \
  || { cat "${TMP}/frompdf.err" >&2; fail "from-pdf 失败"; }
"${OFD}" to-text --input "${TMP}/回环.ofd" --json > "${TMP}/roundtrip.json" || fail "回环 OFD 文本读取失败"
"${PY}" - "${TMP}/frompdf.json" "${TMP}/roundtrip.json" <<'PY' || fail "from-pdf 校验失败"
import json, sys
f = json.load(open(sys.argv[1], encoding="utf-8"))
r = json.load(open(sys.argv[2], encoding="utf-8"))
assert f["pages"] == 2 and r["page_count"] == 2, (f, r["page_count"])
assert f["engine"] in ("text-object", "text-object-outlined", "graphics"), f
assert f["mode"] in ("auto", "text", "graphics"), f
if f["text_searchable"]:
    text = "".join(l["text"] for p in r["pages"] for l in p["lines"])
    assert "电子发票" in text and "第二页" in text, text[:200]
else:
    # auto 模式在文字坐标异常时回退图形化：版式保真、文本不可检索
    assert f["engine"] == "graphics", f
    assert f.get("fallback_reason"), f
PY

# ---------------------------------------------------------------------------
step "9/10 错误处理与退出码（缺文件 2 / 非 OFD 1 / 加密 1）"
run_expect() {
  local expect="$1"; shift
  set +e
  "$@" > "${TMP}/err.out" 2> "${TMP}/err.err"
  local got=$?
  set -e
  [ "${got}" = "${expect}" ] || fail "期望退出码 ${expect}，实际 ${got}: $*"
}
set +e
run_expect 2 "${OFD}" info --input "${TMP}/不存在 的文件.ofd"
grep -q "不存在" "${TMP}/err.err" || fail "缺文件时未给出清晰提示"
printf 'not an ofd\n' > "${TMP}/假文件.ofd"
run_expect 1 "${OFD}" info --input "${TMP}/假文件.ofd"
grep -q "不是有效的 OFD" "${TMP}/err.err" || fail "非 OFD 文件未给出清晰提示"
mkdir -p "${TMP}/enc-src"
printf '<Encryptions/>\n' > "${TMP}/enc-src/Encryptions.xml"
(cd "${TMP}/enc-src" && zip -q "${TMP}/加密 文档.ofd" Encryptions.xml) || fail "无法构造加密样本"
run_expect 1 "${OFD}" info --input "${TMP}/加密 文档.ofd"
grep -q "加密" "${TMP}/err.err" || fail "加密 OFD 未给出清晰提示"
run_expect 2 "${OFD}" merge --input "${TMP}/演示 文档.ofd" --output "${TMP}/单输入.ofd"
run_expect 2 "${OFD}" to-pdf --input "${TMP}/演示 文档.ofd"
set -e

# ---------------------------------------------------------------------------
step "10/10 office-kit 集成入口（bin/office-kit 存在时）"
"${OFD}" --help | grep -q "to-image" || fail "--help 缺少子命令说明"
if [ -x "${KIT_ROOT}/bin/office-kit" ]; then
  "${KIT_ROOT}/bin/office-kit" ofd info --input "${TMP}/演示 文档.ofd" --json > "${TMP}/kit-info.json" \
    || fail "office-kit ofd info 调用失败"
  "${PY}" - "${TMP}/kit-info.json" <<'PY' || fail "office-kit 集成 JSON 校验失败"
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d["pages"] == 2, d["pages"]
PY
  "${KIT_ROOT}/bin/office-kit" ofd --help | grep -q "from-pdf" || fail "office-kit ofd --help 异常"
else
  echo "[ofd-test] 跳过：未找到 ${KIT_ROOT}/bin/office-kit"
fi

# 9.5 方向自检：把 PDF 交给 to-pdf 必须被拦截（退出码 2），而不是报 zip signature
set +e
"${OFD}" to-pdf --input "${TMP}/演示 文档.pdf" --output "${TMP}/wrong.ofd" >/dev/null 2>"${TMP}/wrong.err"
code=$?
set -e
[ "${code}" -eq 2 ] || fail "to-pdf 收到 PDF 输入应退出 2，实际 ${code}"
grep -q "from-pdf" "${TMP}/wrong.err" || fail "方向错误提示里应给出 from-pdf 用法"

printf 'OK ofd\n'
