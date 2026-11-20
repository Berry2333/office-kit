#!/bin/bash
# office-kit ocr 模块自检
#
# 覆盖：
#   1. 用 PyMuPDF 内置 CJK 字体生成中文 PDF（不依赖系统字体文件），做 ocr pdf 并断言关键字；
#   2. 用同一份 fitz 文档导出 PNG，做 ocr image，断言 lines[].box / score；
#   3. --pages 指定页；
#   4. 断网（http_proxy 指到 127.0.0.1:9）再跑一遍；
#   5. list-langs / batch / --output-json / --output-text / --rotate 180；
#   6. 系统有 tesseract 时验证可选后备引擎。
# 成功最后打印 OK ocr。
set -u

SELF="$(readlink -f "$0" 2>/dev/null || echo "$0")"
KIT_ROOT="$(cd "$(dirname "$SELF")/../.." && pwd)"
RUNTIME="${OFFICE_KIT_RUNTIME:-${KIT_ROOT}/runtime}"
PY="${OFFICE_KIT_PY:-${RUNTIME}/python/bin/python3}"
OCR="${KIT_ROOT}/modules/ocr/bin/ocr"

export OFFICE_KIT_ROOT="${KIT_ROOT}"
export OFFICE_KIT_RUNTIME="${RUNTIME}"
export OFFICE_KIT_PY="${PY}"
export OFFICE_KIT_STIRLING="${OFFICE_KIT_STIRLING:-${RUNTIME}/stirling}"

# 每次运行用独立目录，允许并发跑（父子智能体同时自检也不会互相删文件）
WORK="${KIT_ROOT}/.tmp/ocr/test.$$"
rm -rf "$WORK"
mkdir -p "$WORK/data" "$WORK/data/cache" "$WORK/out"
: "${OFFICE_KIT_DATA:=${WORK}/data}"
export OFFICE_KIT_DATA
export OFFICE_KIT_CACHE="${OFFICE_KIT_CACHE:-${OFFICE_KIT_DATA}/cache}"

# 断网语义：所有用例都在“代理指向黑洞”的环境下执行
export http_proxy="http://127.0.0.1:9"
export https_proxy="http://127.0.0.1:9"
export all_proxy="http://127.0.0.1:9"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
export ALL_PROXY="$all_proxy"
export no_proxy="127.0.0.1,localhost"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[ -x "$OCR" ] || fail "找不到可执行入口：$OCR"
[ -x "$PY" ] || fail "找不到运行时 Python：$PY"

echo "== 0. 前置检查 =="
"$OCR" --version >/dev/null || fail "ocr --version 失败"
"$OCR" --help | grep -q "list-langs" || fail "ocr --help 缺少子命令说明"
"$OCR" image --help | grep -q -- "--engine" || fail "ocr image --help 缺少 --engine"
echo "   入口/帮助 OK：$("$OCR" --version)"

echo "== 1. 生成测试数据（fitz 内置 CJK 字体，不依赖系统字体） =="
"$PY" - "$WORK" <<'PY'
import os
import sys

try:
    import pymupdf as fitz
except ImportError:  # 旧版 PyMuPDF 只有 fitz 模块名
    import fitz

work = sys.argv[1]
pdf_path = os.path.join(work, "扫描件 中文.pdf")

doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_text((72, 110), "离线办公 OCR 测试报告", fontsize=22, fontname="china-s")
page.insert_text((72, 160), "发票号码: 12345678", fontsize=16, fontname="china-s")
page.insert_text((72, 200), "合计金额: 1234.56 元", fontsize=16, fontname="china-s")
page.insert_text((72, 240), "Office Kit Offline OCR Test 2026", fontsize=16, fontname="helv")

page2 = doc.new_page(width=595, height=842)
page2.insert_text((72, 110), "第二页 测试内容", fontsize=22, fontname="china-s")
page2.insert_text((72, 160), "PAGE-TWO-KEYWORD", fontsize=16, fontname="helv")

doc.save(pdf_path)
doc.close()

# 用同一份文档导出 PNG，给 ocr image 用（含中文与空格的路径）
doc = fitz.open(pdf_path)
pix = doc[0].get_pixmap(dpi=200, colorspace=fitz.csRGB, alpha=False)
png_path = os.path.join(work, "页面 1.png")
pix.save(png_path)
doc.close()
print(f"   PDF: {pdf_path}")
print(f"   PNG: {png_path} ({pix.width}x{pix.height})")
PY
[ -s "$WORK/扫描件 中文.pdf" ] || fail "测试 PDF 未生成"
[ -s "$WORK/页面 1.png" ] || fail "测试 PNG 未生成"

echo "== 2. ocr pdf：关键字 + JSON 结构 =="
"$OCR" pdf --input "$WORK/扫描件 中文.pdf" --json \
  --output-json "$WORK/out/pdf.json" --output-text "$WORK/out/pdf.txt" \
  > "$WORK/out/pdf.stdout.json" 2> "$WORK/out/pdf.stderr.log" \
  || fail "ocr pdf 退出码非 0（见 $WORK/out/pdf.stderr.log）"

"$PY" - "$WORK/out/pdf.stdout.json" "$WORK/out/pdf.json" "$WORK/out/pdf.txt" <<'PY'
import json
import sys

stdout_path, json_path, txt_path = sys.argv[1:4]
raw = open(stdout_path, encoding="utf-8").read()
data = json.loads(raw)
saved = json.load(open(json_path, encoding="utf-8"))

assert data["engine"] in ("rapid", "tess"), data["engine"]
assert data["input"].endswith("扫描件 中文.pdf"), data["input"]
assert len(data["pages"]) == 2, len(data["pages"])
assert data["page_count"] == 2
assert data["dpi"] == 200 and abs(data["pixels_per_point"] - 200 / 72.0) < 1e-3

for index, page in enumerate(data["pages"], 1):
    assert page["page"] == index, page["page"]
    assert page["dpi"] == 200, page["dpi"]
    assert abs(page["pixels_per_point"] - 200 / 72.0) < 1e-3
    assert page["width"] > 1000 and page["height"] > 1500, (page["width"], page["height"])
    lines = page["lines"]
    assert len(lines) >= 2, (index, len(lines))
    assert page["text"] == "\n".join(line["text"] for line in lines)
    for line in lines:
        assert isinstance(line["text"], str) and line["text"].strip()
        box = line["box"]
        assert len(box) == 4, box
        assert all(isinstance(v, (int, float)) for v in box), box
        x1, y1, x2, y2 = box
        assert 0 <= x1 < x2 <= page["width"], box
        assert 0 <= y1 < y2 <= page["height"], box
        assert 0.0 <= line["score"] <= 1.0, line["score"]
        assert line["page"] == index

page_one = data["pages"][0]
lines = page_one["lines"]
assert any(line["score"] > 0.5 for line in lines), "所有行置信度都偏低"

text = data["text"]
for keyword in ("离线办公", "发票", "12345678", "Office"):
    assert keyword in text, (keyword, text)

assert saved["engine"] == data["engine"] and saved["text"] == data["text"]
assert open(txt_path, encoding="utf-8").read().strip() == data["text"].strip()
print(f"   pdf OK：{len(lines)} 行，{len(text)} 字，引擎 {data['engine']}，"
      f"首行置信度 {lines[0]['score']}")
PY
[ $? -eq 0 ] || fail "ocr pdf 结果断言失败"

echo "== 3. ocr pdf --pages 2：指定页 =="
"$OCR" pdf --input "$WORK/扫描件 中文.pdf" --pages 2 --json \
  > "$WORK/out/pdf-page2.json" 2> "$WORK/out/pdf-page2.err" \
  || fail "ocr pdf --pages 2 失败（见 $WORK/out/pdf-page2.err）"
"$PY" - "$WORK/out/pdf-page2.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
assert len(data["pages"]) == 1, len(data["pages"])
page = data["pages"][0]
assert page["page"] == 2, page["page"]
assert "第二页" in page["text"], page["text"]
assert "PAGE-TWO-KEYWORD" in page["text"], page["text"]
assert all(line["page"] == 2 for line in page["lines"])
assert data["page_count"] == 2, data["page_count"]
print(f"   pages OK：第 2 页 {len(page['lines'])} 行 -> {page['text']!r}")
PY
[ $? -eq 0 ] || fail "ocr pdf --pages 断言失败"

echo "== 4. ocr image：PNG + lines[].box/score =="
"$OCR" image --input "$WORK/页面 1.png" --json \
  > "$WORK/out/image.json" 2> "$WORK/out/image.err" \
  || fail "ocr image 失败（见 $WORK/out/image.err）"
"$PY" - "$WORK/out/image.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
page = data["pages"][0]
assert page["page"] == 1
assert data["engine"] in ("rapid", "tess")
text = data["text"]
assert "离线办公" in text, text
assert "发票" in text, text

lines = page["lines"]
assert len(lines) >= 3, len(lines)
for line in lines:
    box = line["box"]
    assert len(box) == 4
    assert 0 <= box[0] < box[2] <= page["width"]
    assert 0 <= box[1] < box[3] <= page["height"]
    assert 0.0 <= line["score"] <= 1.0
assert page["width"] == 1653 and page["height"] == 2339, (page["width"], page["height"])
print(f"   image OK：{page['width']}x{page['height']}，{len(lines)} 行，"
      f"最高置信度 {max(l['score'] for l in lines)}")
PY
[ $? -eq 0 ] || fail "ocr image 断言失败"

echo "== 5. 断网显式复测（http_proxy=127.0.0.1:9） =="
env http_proxy="http://127.0.0.1:9" https_proxy="http://127.0.0.1:9" \
    all_proxy="http://127.0.0.1:9" HTTP_PROXY="http://127.0.0.1:9" \
    HTTPS_PROXY="http://127.0.0.1:9" ALL_PROXY="http://127.0.0.1:9" \
    "$OCR" image --input "$WORK/页面 1.png" --engine rapid --json \
    > "$WORK/out/offline.json" 2> "$WORK/out/offline.err" \
  || fail "断网环境识别失败（若 RapidOCR 尝试联网下载模型会在此暴露）"
"$PY" - "$WORK/out/offline.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["engine"] == "rapid", data["engine"]
assert "离线办公" in data["text"], data["text"]
print(f"   断网 OK：引擎 {data['engine']}，{len(data['text'])} 字（模型随包，无下载）")
PY
[ $? -eq 0 ] || fail "断网断言失败"

echo "== 6. list-langs（人类可读 + JSON） =="
"$OCR" list-langs > "$WORK/out/langs.txt" 2> "$WORK/out/langs.err" || fail "list-langs 失败"
grep -q "rapid" "$WORK/out/langs.txt" || fail "list-langs 未列出 rapid"
"$OCR" list-langs --json > "$WORK/out/langs.json" 2>> "$WORK/out/langs.err" \
  || fail "list-langs --json 失败"
"$PY" - "$WORK/out/langs.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
assert "engines" in data and "languages" in data
rapid = data["engines"]["rapid"]
assert rapid["available"], rapid
assert "chi_sim" in rapid["languages"], rapid
codes = [item["code"] for item in data["languages"]]
assert "chi_sim" in codes and "eng" in codes, codes
print(f"   list-langs OK：rapid {rapid['version']}，"
      f"tess {'可用' if data['engines']['tess']['available'] else '不可用'}")
PY
[ $? -eq 0 ] || fail "list-langs JSON 断言失败"

echo "== 7. batch：目录（含中文/空格）+ 失败隔离 + --output-dir =="
mkdir -p "$WORK/批量 目录/子目录"
cp "$WORK/页面 1.png" "$WORK/批量 目录/甲 图片.png"
cp "$WORK/扫描件 中文.pdf" "$WORK/批量 目录/子目录/乙 文档.pdf"
printf 'not an image' > "$WORK/批量 目录/坏文件.png"
"$OCR" batch --input "$WORK/批量 目录" --recursive --json \
  --output-dir "$WORK/批量输出" \
  > "$WORK/out/batch.json" 2> "$WORK/out/batch.err" \
  || fail "ocr batch 失败（见 $WORK/out/batch.err）"
"$PY" - "$WORK/out/batch.json" "$WORK/批量输出" <<'PY'
import json
import os
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
assert set(data) >= {"failures", "items"}, sorted(data)
assert len(data["items"]) == 2, [item["input"] for item in data["items"]]
assert len(data["failures"]) == 1, data["failures"]
assert data["failures"][0]["input"].endswith("坏文件.png")
for item in data["items"]:
    assert item["pages"] and item["text"], item["input"]
    assert item["engine"] == data["engine"]
out_dir = sys.argv[2]
files = os.listdir(out_dir)
assert len(files) == 4, files
assert any(name.endswith(".json") for name in files)
assert any(name.endswith(".txt") for name in files)
print(f"   batch OK：{len(data['items'])} 成功 / {len(data['failures'])} 失败，"
      f"逐文件输出 {len(files)} 个")
PY
[ $? -eq 0 ] || fail "batch 断言失败"

echo "== 8. --rotate 180 方向矫正 =="
"$PY" - "$WORK/页面 1.png" "$WORK/页面 1-倒置.png" <<'PY'
import sys

from PIL import Image

source, target = sys.argv[1:3]
with Image.open(source) as handle:
    handle.convert("RGB").rotate(-180, expand=True).save(target)
print(f"   生成倒置图: {target}")
PY
"$OCR" image --input "$WORK/页面 1-倒置.png" --rotate auto --json \
  > "$WORK/out/rotate.json" 2> "$WORK/out/rotate.err" \
  || fail "ocr image --rotate auto 失败（见 $WORK/out/rotate.err）"
"$PY" - "$WORK/out/rotate.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data.get("rotation"), "未检测/应用旋转"
assert data["rotation"]["angle"] % 360 == 180, data["rotation"]
assert "离线办公" in data["text"], data["text"]
page = data["pages"][0]
assert page["width"] == 1653 and page["height"] == 2339
print(f"   rotate OK：{data['rotation']}，{len(page['lines'])} 行")
PY
[ $? -eq 0 ] || fail "rotate 断言失败"

echo "== 9. 可选后备引擎 tesseract（存在才测） =="
if command -v tesseract >/dev/null 2>&1 && tesseract --list-langs 2>/dev/null | grep -q chi_sim; then
  "$OCR" image --input "$WORK/页面 1.png" --engine tess --json \
    > "$WORK/out/tess.json" 2> "$WORK/out/tess.err" \
    || fail "ocr image --engine tess 失败（见 $WORK/out/tess.err）"
  "$PY" - "$WORK/out/tess.json" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["engine"] == "tess"
assert "离线办公" in data["text"], data["text"]
assert data["pages"][0]["lines"]
print(f"   tesseract OK：{len(data['pages'][0]['lines'])} 行")
PY
  [ $? -eq 0 ] || fail "tesseract 断言失败"
else
  echo "   跳过：系统 tesseract 无 chi_sim"
fi

echo
echo "测试产物：$WORK"
echo "OK ocr"
