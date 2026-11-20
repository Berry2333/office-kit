#!/bin/bash
# modules/pdf/test.sh — pdf 模块自检
#
# 覆盖：start/stop/status、list-tools（真实 OpenAPI）、merge、split、rotate、
# extract-text、pdf-to-img、img-to-pdf、compress、encrypt、decrypt、watermark、
# ocr（tesseract chi_sim）、pdf-to-pdfa、info/summary、中文与空格路径、错误码。
#
# 依赖：runtime/python 中的 PyMuPDF（仅测试用，生成/校验 PDF），不依赖系统 poppler。
# 成功时最后一行打印 "OK pdf"。
set -uo pipefail

SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"
MODULE="$(cd "$(dirname "$SELF")" && pwd)"
KIT_ROOT="${OFFICE_KIT_ROOT:-$(cd "$MODULE/../.." && pwd)}"
RUNTIME="${OFFICE_KIT_RUNTIME:-$KIT_ROOT/runtime}"

# 隔离的数据目录：不污染用户真实的 $OFFICE_KIT_DATA，也不受其影响
WORK="$KIT_ROOT/.tmp/pdf-test"
rm -rf "$WORK"
mkdir -p "$WORK/data" "$WORK/in" "$WORK/out" "$WORK/logs"
export OFFICE_KIT_ROOT="$KIT_ROOT"
export OFFICE_KIT_RUNTIME="$RUNTIME"
export OFFICE_KIT_DATA="$WORK/data"
export OFFICE_KIT_CACHE="$WORK/data/cache"
export OFFICE_KIT_LOGS="$WORK/logs"
export OFFICE_KIT_PY="${OFFICE_KIT_PY:-$RUNTIME/python/bin/python3}"
export OFFICE_KIT_JAVA="${OFFICE_KIT_JAVA:-$RUNTIME/jre/bin/java}"
export OFFICE_KIT_STIRLING="${OFFICE_KIT_STIRLING:-$RUNTIME/stirling}"
export OFFICE_KIT_PDF_MODULE="$MODULE"
export OFFICE_KIT_LANG="${OFFICE_KIT_LANG:-zh_CN}"
# 允许测试使用模块自带 Python 依赖（若 runtime 未装）
if [ -d "$MODULE/lib/py" ]; then
  export PYTHONPATH="$MODULE/lib/py${PYTHONPATH:+:$PYTHONPATH}"
fi

if [ -x "$KIT_ROOT/bin/office-kit" ]; then
  PDF=("$KIT_ROOT/bin/office-kit" pdf)
else
  PDF=("$MODULE/bin/pdf")
fi

fail() { echo "FAIL: $*" >&2; exit 1; }

# 可选系统依赖：存在则测，缺失则 SKIP（不算失败）
HAVE_TESS=0
command -v tesseract >/dev/null 2>&1 && HAVE_TESS=1
HAVE_GS=0
command -v gs >/dev/null 2>&1 && HAVE_GS=1
OCR_MODULE="$KIT_ROOT/modules/ocr/bin/ocr"
[ -x "$OCR_MODULE" ] || OCR_MODULE=""
echo "== 可选依赖：tesseract=$HAVE_TESS ghostscript=$HAVE_GS 内置OCR=$([ -n "$OCR_MODULE" ] && echo yes || echo no)"

cleanup() {
  "${PDF[@]}" stop --json >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== 检查 Python / PyMuPDF"
"$OFFICE_KIT_PY" - <<'PY' || fail "需要 PyMuPDF：runtime/python 或 modules/pdf/lib/py 中未找到 pymupdf"
try:
    import pymupdf
except ImportError:
    import fitz as pymupdf
print("   PyMuPDF", pymupdf.__doc__.splitlines()[0] if pymupdf.__doc__ else "")
PY

echo "== 生成测试 PDF（中文 + 空格文件名）"
"$OFFICE_KIT_PY" - "$WORK/in" <<'PY' || fail "生成测试 PDF 失败"
import sys
from pathlib import Path
try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

out = Path(sys.argv[1])
doc = pymupdf.open()
for i in range(3):
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 120), f"Office Kit PDF 测试 第 {i+1} 页", fontname="china-s", fontsize=22)
    page.insert_text((72, 170), f"Hello Stirling PDF page {i+1}", fontname="helv", fontsize=16)
    page.insert_text((72, 210), "这是用于验证文本抽取与 OCR 的中文内容。", fontname="china-s", fontsize=14)
doc.save(out / "报告 三页.pdf")
doc.close()

doc = pymupdf.open()
for i in range(2):
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 120), f"Second Document Page {i+1}", fontname="helv", fontsize=22)
doc.save(out / "第二个 文档.pdf")
doc.close()

# 扫描件模型：中文渲染成图片后再放回 PDF，没有文字层
src = pymupdf.open(out / "报告 三页.pdf")
scan = pymupdf.open()
for i in range(2):
    pix = src[i].get_pixmap(dpi=100)
    page = scan.new_page(width=595, height=842)
    page.insert_image(page.rect, pixmap=pix)
scan.save(out / "扫描件 无文本.pdf")
scan.close()

# 图片输入
for i in range(2):
    src[i].get_pixmap(dpi=100).save(out / f"页面 图片 {i+1}.png")
src.close()
print("   已生成：", ", ".join(sorted(p.name for p in out.iterdir())))
PY

echo "== start（首次启动较慢）"
"${PDF[@]}" start --idle-timeout 0 --json >"$WORK/01-start.json" || fail "pdf start"
"$OFFICE_KIT_PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["ok"] and d["running"] and d["port"]>0, d; print("   端口", d["port"], "版本", d["version"])' "$WORK/01-start.json" || fail "start JSON"

echo "== start 复用"
"${PDF[@]}" start --json >"$WORK/02-reuse.json" || fail "pdf start（复用）"
"$OFFICE_KIT_PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["ok"] and d["reused"], d' "$WORK/02-reuse.json" || fail "start 未复用"

echo "== status"
"${PDF[@]}" status --json >"$WORK/03-status.json" || fail "pdf status"
"$OFFICE_KIT_PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["running"] and d["ready"] and d["pid"] and d["port"], d' "$WORK/03-status.json" || fail "status JSON"

echo "== list-tools（必须来自真实 OpenAPI）"
"${PDF[@]}" list-tools --json >"$WORK/04-tools.json" || fail "pdf list-tools"
"$OFFICE_KIT_PY" - "$WORK/04-tools.json" <<'PY' || fail "工具清单不完整"
import json, sys
d = json.load(open(sys.argv[1]))
assert d["ok"], d
tools = {t["tool"]: t for t in d["tools"]}
assert len(tools) >= 100, len(tools)
required = ["merge","split","rotate","extract-text","pdf-to-img","img-to-pdf",
            "compress","encrypt","decrypt","watermark","ocr","pdf-to-pdfa","info"]
missing = [x for x in required if x not in tools]
assert not missing, missing
for name in required:
    t = tools[name]
    assert t["path"].startswith("/api/v1/"), t
    assert t["operationId"], t
assert tools["merge"]["path"] == "/api/v1/general/merge-pdfs", tools["merge"]["path"]
assert tools["ocr"]["path"] == "/api/v1/misc/ocr-pdf", tools["ocr"]["path"]
print("   共", len(tools), "个端点；必测工具齐全")
PY

IN1="$WORK/in/报告 三页.pdf"
IN2="$WORK/in/第二个 文档.pdf"
SCAN="$WORK/in/扫描件 无文本.pdf"
IMG1="$WORK/in/页面 图片 1.png"
IMG2="$WORK/in/页面 图片 2.png"
OUT="$WORK/out"

echo "== merge"
"${PDF[@]}" run merge --input "$IN1" --input "$IN2" --output "$OUT/合并 结果.pdf" --json >"$WORK/10-merge.json" || fail "merge"
echo "== split"
"${PDF[@]}" run split --input "$IN1" --option pageNumbers=all --output-dir "$OUT/拆分 目录" --json >"$WORK/11-split.json" || fail "split"
echo "== rotate（同时验证人类可读输出=文件路径）"
ROT="$OUT/旋转 结果.pdf"
ROT_OUT="$("${PDF[@]}" run rotate --input "$IN1" --option angle=90 --output "$ROT")" || fail "rotate"
[ "$ROT_OUT" = "$ROT" ] || fail "rotate 未打印输出路径：$ROT_OUT"
echo "== extract-text"
"${PDF[@]}" run extract-text --input "$IN1" --output "$OUT/文本 结果.txt" --json >"$WORK/13-text.json" || fail "extract-text"
echo "== pdf-to-img"
"${PDF[@]}" run pdf-to-img --input "$IN1" --option dpi=100 --output-dir "$OUT/图片 输出" --json >"$WORK/14-img.json" || fail "pdf-to-img"
echo "== img-to-pdf"
"${PDF[@]}" run img-to-pdf --input "$IMG1" --input "$IMG2" --output "$OUT/图片合成.pdf" --json >"$WORK/15-i2p.json" || fail "img-to-pdf"
echo "== compress"
"${PDF[@]}" run compress --input "$SCAN" --option optimizeLevel=5 --output "$OUT/压缩 结果.pdf" --json >"$WORK/16-compress.json" || fail "compress"
echo "== encrypt"
"${PDF[@]}" run encrypt --input "$IN1" --option password=secret123 --output "$OUT/加密.pdf" --json >"$WORK/17-encrypt.json" || fail "encrypt"
echo "== decrypt"
"${PDF[@]}" run decrypt --input "$OUT/加密.pdf" --option password=secret123 --output "$OUT/解密.pdf" --json >"$WORK/18-decrypt.json" || fail "decrypt"
echo "== watermark"
"${PDF[@]}" run watermark --input "$IN1" --option watermarkText="机密 CONFIDENTIAL" --option opacity=0.25 --output "$OUT/水印.pdf" --json >"$WORK/19-watermark.json" || fail "watermark"
echo "== ocr"
if [ "$HAVE_TESS" = 1 ]; then
  "${PDF[@]}" run ocr --input "$SCAN" --option languages=chi_sim+eng \
    --option ocrType=force-ocr --output "$OUT/OCR 结果.pdf" --json >"$WORK/20-ocr.json" \
    || fail "ocr（tesseract）"
elif [ -n "$OCR_MODULE" ]; then
  echo "   系统无 tesseract，自动走内置 RapidOCR"
  "${PDF[@]}" run ocr --input "$SCAN" --option languages=chi_sim+eng \
    --output "$OUT/OCR 结果.pdf" --json >"$WORK/20-ocr.json" || fail "ocr（RapidOCR 兜底）"
else
  echo "   SKIP：系统无 tesseract，且 modules/ocr 不可用"
  touch "$WORK/skip-ocr"
fi

if [ -n "$OCR_MODULE" ]; then
  echo "== ocr 内置后备（强制 RapidOCR，不依赖 tesseract）"
  OFFICE_KIT_PDF_OCR_ENGINE=rapidocr "${PDF[@]}" run ocr --input "$SCAN" \
    --option languages=chi_sim+eng --output "$OUT/OCR 后备.pdf" \
    --json >"$WORK/20b-ocr-fallback.json" || fail "ocr 内置后备"
fi

echo "== pdf-to-pdfa"
if [ "$HAVE_GS" = 1 ]; then
  "${PDF[@]}" run pdf-to-pdfa --input "$IN1" --output "$OUT/PDFA 结果.pdf" \
    --json >"$WORK/21-pdfa.json" || fail "pdf-to-pdfa"
else
  echo "   SKIP：系统无 ghostscript"
  touch "$WORK/skip-pdfa"
fi
echo "== info / summary"
"${PDF[@]}" run info --input "$IN1" --json >"$WORK/22-info.json" || fail "info"
"${PDF[@]}" run summary --input "$IN1" --json >"$WORK/23-summary.json" || fail "summary"

echo "== 错误码：未知工具应为 2"
if "${PDF[@]}" run no-such-tool --input "$IN1" --json >"$WORK/24-unknown.json" 2>/dev/null; then
  fail "未知工具应返回非 0"
fi
"$OFFICE_KIT_PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["ok"] is False and d["error"]["message"], d' "$WORK/24-unknown.json" || fail "错误 JSON"

echo "== stop"
"${PDF[@]}" stop --json >"$WORK/30-stop.json" || fail "pdf stop"
"${PDF[@]}" status --json >"$WORK/31-status.json" || fail "status after stop"
"$OFFICE_KIT_PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["ok"] and not d["running"], d' "$WORK/31-status.json" || fail "stop 后仍在运行"

echo "== 校验输出文件（PyMuPDF）"
"$OFFICE_KIT_PY" - "$WORK" <<'PY' || fail "输出校验失败"
import json
import re
import sys
from pathlib import Path
try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

work = Path(sys.argv[1])
out = work / "out"

def load(p):
    d = pymupdf.open(str(p))
    return d

def pages(p):
    with load(p) as d:
        return len(d)

def text(p, page=0, password=None):
    with load(p) as d:
        if password:
            assert d.authenticate(password), "密码错误"
        return d[page].get_text()

def ok_json(name):
    with open(work / name, encoding="utf-8") as f:
        d = json.load(f)
    assert d.get("ok") is True, (name, d)
    return d

# 各命令的 JSON 契约
for name in ["10-merge.json","11-split.json","13-text.json","14-img.json","15-i2p.json",
             "16-compress.json","17-encrypt.json","18-decrypt.json","19-watermark.json",
             "22-info.json","23-summary.json"]:
    ok_json(name)
for name in ["20-ocr.json", "20b-ocr-fallback.json", "21-pdfa.json"]:
    if (work / name).exists():
        ok_json(name)

merge = ok_json("10-merge.json")
assert pages(out / "合并 结果.pdf") == 5, pages(out / "合并 结果.pdf")
assert "Hello Stirling" in text(out / "合并 结果.pdf")
assert "第 1 页" in text(out / "合并 结果.pdf")
assert merge["outputs"] and Path(merge["outputs"][0]).exists()

split_files = sorted((out / "拆分 目录").glob("*.pdf"))
assert len(split_files) == 3, split_files
for f in split_files:
    assert pages(f) == 1, f

rot = load(out / "旋转 结果.pdf")
assert len(rot) == 3 and all(page.rotation == 90 for page in rot), [p.rotation for p in rot]
rot.close()

txt = (out / "文本 结果.txt").read_text(encoding="utf-8")
assert "Office Kit" in txt and "中文内容" in txt, txt[:200]

pngs = sorted((out / "图片 输出").glob("*.png"))
assert len(pngs) == 3, pngs
for p in pngs:
    assert p.stat().st_size > 1000, p
    pix = pymupdf.Pixmap(str(p))
    assert pix.width > 100 and pix.height > 100, p

assert pages(out / "图片合成.pdf") == 2
assert pages(out / "压缩 结果.pdf") == 2
assert (out / "压缩 结果.pdf").stat().st_size < (work / "in/扫描件 无文本.pdf").stat().st_size

enc = load(out / "加密.pdf")
assert enc.is_encrypted and enc.needs_pass, "加密.pdf 未加密"
enc.close()
assert pages(out / "解密.pdf") == 3
assert not load(out / "解密.pdf").is_encrypted
assert "机密" in text(out / "水印.pdf").replace(" ", "") or "CONFIDENTIAL" in text(out / "水印.pdf")

if not (work / "skip-ocr").exists():
    ocr_doc = load(out / "OCR 结果.pdf")
    assert len(ocr_doc) == 2
    ocr_text = ocr_doc[0].get_text()
    assert re.search(r"[\u4e00-\u9fff]", ocr_text), ocr_text[:200]
    assert "Hello" in ocr_text or "Office" in ocr_text, ocr_text[:200]
    ocr_doc.close()

if (work / "20b-ocr-fallback.json").exists():
    fb = ok_json("20b-ocr-fallback.json")
    assert fb["details"].get("engine") == "rapidocr", fb["details"].get("engine")
    assert fb["details"].get("fallback") is True, fb["details"]
    fb_doc = load(out / "OCR 后备.pdf")
    fb_text = fb_doc[0].get_text()
    assert re.search(r"[\u4e00-\u9fff]", fb_text), fb_text[:200]
    fb_doc.close()

if not (work / "skip-pdfa").exists():
    pdfa = out / "PDFA 结果.pdf"
    assert pages(pdfa) == 3
    blob = pdfa.read_bytes()
    assert b"pdfaid:part" in blob, "缺少 PDF/A 标识"
    assert re.search(rb"pdfaid:part=['\"]2['\"]", blob), "不是 PDF/A-2"
else:
    print("   （跳过 PDF/A 校验：无 ghostscript）")
if (work / "skip-ocr").exists():
    print("   （跳过 OCR 校验：无 tesseract 且无内置 OCR）")

info = ok_json("22-info.json")
assert info["details"]["data"]["pageCount"] == 3, info
summary = ok_json("23-summary.json")
assert summary["details"]["data"]["basic"]["pageCount"] == 3, summary

start = json.load(open(work / "01-start.json", encoding="utf-8"))
assert start["port"] > 0 and start["version"]
stop = json.load(open(work / "30-stop.json", encoding="utf-8"))
assert stop["ok"] and stop["stopped"]

pdfa_note = "；PDF-A 已跳过" if (work / "skip-pdfa").exists() else "/PDF-A"
print(f"   全部输出校验通过（页数/文本/加密/旋转/OCR{pdfa_note}）")
PY

echo
echo "OK pdf"
