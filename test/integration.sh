#!/bin/bash
# office-kit 端到端集成验收：5 个模块串起来跑一遍真实业务流
#
#   bash test/integration.sh            # 仓库模式（bin/office-kit）
#   KIT_APPIMAGE=dist/xxx.AppImage bash test/integration.sh   # AppImage 模式
#
# 通过打印 PASS，退出码 0。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/office-kit-it.XXXXXX")"
PY="${OFFICE_KIT_PY:-$ROOT/runtime/python/bin/python3}"
trap 'rm -rf "$WORK"' EXIT

if [ -n "${KIT_APPIMAGE:-}" ]; then
  APP="$(readlink -f "$KIT_APPIMAGE")"
  if [ "${OFFICE_KIT_EXTRACT:-0}" = "1" ]; then
    KIT=(env APPIMAGE_EXTRACT_AND_RUN=1 "$APP")
  else
    KIT=("$APP")
  fi
  export OFFICE_KIT_DATA="$WORK/data"
else
  KIT=("$ROOT/bin/office-kit")
fi

pass=0 fail=0
ok()  { printf '  \033[32mok\033[0m   %s\n' "$*"; pass=$((pass+1)); }
bad() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fail=$((fail+1)); }
step(){ printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
need(){ [ -s "$1" ] || { bad "缺少输出 $1"; return 1; }; }

step "0. CLI 基本约定"
"${KIT[@]}" --version >/dev/null 2>&1 && ok "--version" || bad "--version"
[ "$("${KIT[@]}" list | wc -l)" -eq 5 ] && ok "list 输出 5 个分组" || bad "list 分组数不为 5"
for g in office pdf ofd ocr asr; do
  "${KIT[@]}" "$g" --help >/dev/null 2>&1 && ok "$g --help" || bad "$g --help"
done

step "1. office：结构化生成 → PDF → 渲染 → 摘要"
cat > "$WORK/docx.json" <<'JSON'
{"title":"2026 年度离线办公测试","subtitle":"office-kit 集成验收",
 "paragraphs":["这是一段中文正文，包含标点、数字 12345 与 English words。",
               "第二段用于验证多段落与字体回退。"],
 "tables":[{"headers":["模块","状态","说明"],"rows":[["office","通过","LibreOffice WASM"],["pdf","通过","Stirling-PDF"],["ofd","通过","ofdrw"]]}]}
JSON
cat > "$WORK/xlsx.json" <<'JSON'
{"sheets":[{"name":"预算","rows":[["项目","单价","数量","金额"],
  ["办公文档工具箱",123.45,2,null],["OCR 模块",0,1,null]],
  "formulas":{"D2":"=B2*C2","D3":"=B3*C3"},"widths":{"A":22,"B":10,"C":8,"D":12}}]}
JSON
cat > "$WORK/pptx.json" <<'JSON'
{"slides":[{"title":"离线办公套件","bullets":["Word / Excel / PPT","PDF 50+ 工具","OFD 版式文档","OCR 与语音"]},
           {"title":"架构","bullets":["单一 AppImage","零网络依赖","DSH 技能封装"]}]}
JSON
"${KIT[@]}" office create --type docx --output "$WORK/报告 中文.docx" --plan "$WORK/docx.json" --json >"$WORK/c1.json" 2>"$WORK/c1.err" \
  && ok "create docx" || { bad "create docx"; cat "$WORK/c1.err"; }
"${KIT[@]}" office create --type xlsx --output "$WORK/预算.xlsx" --plan "$WORK/xlsx.json" --json >/dev/null 2>&1 \
  && ok "create xlsx" || bad "create xlsx"
"${KIT[@]}" office create --type pptx --output "$WORK/汇报.pptx" --plan "$WORK/pptx.json" --json >/dev/null 2>&1 \
  && ok "create pptx" || bad "create pptx"

"${KIT[@]}" office convert --input "$WORK/报告 中文.docx" --output "$WORK/报告.pdf" --json >"$WORK/conv.json" 2>"$WORK/conv.err" \
  && need "$WORK/报告.pdf" && ok "docx -> pdf" || { bad "docx -> pdf"; tail -5 "$WORK/conv.err"; }
"${KIT[@]}" office render --input "$WORK/汇报.pptx" --output-dir "$WORK/ppt-png" --pages 1 --dpi 120 --json >"$WORK/render.json" 2>&1 \
  && ls "$WORK/ppt-png"/*.png >/dev/null 2>&1 && ok "pptx 渲染 PNG" || bad "pptx 渲染 PNG"
"${KIT[@]}" office info --input "$WORK/报告 中文.docx" --json >"$WORK/info.json" 2>&1 \
  && "$PY" -c "import json;d=json.load(open('$WORK/info.json'));assert d['format']=='docx'" 2>/dev/null \
  && ok "docx info" || bad "docx info"
"${KIT[@]}" office recalc --input "$WORK/预算.xlsx" --output "$WORK/预算-重算.xlsx" --json >/dev/null 2>&1 \
  && ok "xlsx recalc" || bad "xlsx recalc"

step "1b. WPS：.et 表格与 .wps 文档"
"$PY" - "$WORK" <<'PY'
import sys, xlwt
wb = xlwt.Workbook(); ws = wb.add_sheet("预算")
for r, row in enumerate([["项目","数量","单价"],["办公",2,123.45],["文档",1,10]]):
    for c, v in enumerate(row): ws.write(r, c, v)
ws.write(1, 3, xlwt.Formula("B2*C2"))
wb.save(sys.argv[1] + "/wps.xls")
PY
cp "$WORK/wps.xls" "$WORK/预算 表格.et"
"${KIT[@]}" office info --input "$WORK/预算 表格.et" --json >"$WORK/et-info.json" 2>/dev/null \
  && "$PY" -c "import json;d=json.load(open('$WORK/et-info.json'));assert d['sourceFormat']=='et'" 2>/dev/null \
  && ok "WPS 表格 .et 识别" || bad "WPS 表格 .et 识别"
"${KIT[@]}" office convert --input "$WORK/预算 表格.et" --output "$WORK/et.pdf" --json >/dev/null 2>&1 \
  && need "$WORK/et.pdf" && ok "WPS .et -> PDF" || bad "WPS .et -> PDF"
WPS_SAMPLE="${WPS_FIXTURE:-$ROOT/AI边缘计算盒子研究报告附件册.wps}"
if [ -f "$WPS_SAMPLE" ]; then
  "${KIT[@]}" office convert --input "$WPS_SAMPLE" --output "$WORK/wps.pdf" --json >/dev/null 2>&1 \
    && need "$WORK/wps.pdf" && ok "WPS .wps -> PDF" || bad "WPS .wps -> PDF"
  "${KIT[@]}" office render --input "$WPS_SAMPLE" --output-dir "$WORK/wps-png" --pages 1 --dpi 72 --json >/dev/null 2>&1 \
    && ls "$WORK/wps-png"/*.png >/dev/null 2>&1 && ok "WPS .wps 渲染" || bad "WPS .wps 渲染"
else
  echo "  skip WPS .wps（无样本）"
fi

step "2. ocr：扫描件/图片识别（含坐标）"
"${KIT[@]}" ocr pdf --input "$WORK/报告.pdf" --pages 1 --json >"$WORK/ocr.json" 2>"$WORK/ocr.err" \
  && "$PY" - "$WORK/ocr.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
assert d["pages"] and d["pages"][0]["lines"], "缺少 lines"
assert "离线" in d["text"] or "办公" in d["text"], d["text"][:100]
box=d["pages"][0]["lines"][0]["box"]; assert len(box)==4
PY
ok "ocr pdf 中文识别 + 坐标" || { bad "ocr pdf"; tail -3 "$WORK/ocr.err"; }
ls "$WORK/ppt-png"/*.png >/dev/null 2>&1 && {
  "${KIT[@]}" ocr image --input "$WORK/ppt-png/page-001.png" --json >"$WORK/ocri.json" 2>/dev/null \
    && ok "ocr image" || bad "ocr image"
}

step "3. ofd：生成样例 → 解析 → 转 PDF / 图片 / 文本 / 合并"
"${KIT[@]}" ofd demo --output "$WORK/样例.ofd" --json >/dev/null 2>&1 && ok "ofd demo 生成" || bad "ofd demo 生成"
"${KIT[@]}" ofd info --input "$WORK/样例.ofd" --json >"$WORK/ofdinfo.json" 2>&1 \
  && "$PY" -c "import json;d=json.load(open('$WORK/ofdinfo.json'));assert d['pages']>=1" 2>/dev/null \
  && ok "ofd info" || bad "ofd info"
"${KIT[@]}" ofd to-pdf --input "$WORK/样例.ofd" --output "$WORK/样例.pdf" --json >/dev/null 2>&1 \
  && need "$WORK/样例.pdf" && ok "ofd -> pdf" || bad "ofd -> pdf"
"${KIT[@]}" ofd to-image --input "$WORK/样例.ofd" --output-dir "$WORK/ofd-png" --dpi 120 --json >/dev/null 2>&1 \
  && ls "$WORK/ofd-png"/*.png >/dev/null 2>&1 && ok "ofd -> png" || bad "ofd -> png"
"${KIT[@]}" ofd to-text --input "$WORK/样例.ofd" --json >"$WORK/ofdtext.json" 2>&1 \
  && grep -q "发票\|OFD" "$WORK/ofdtext.json" && ok "ofd -> text" || bad "ofd -> text"
"${KIT[@]}" ofd merge --input "$WORK/样例.ofd" --input "$WORK/样例.ofd" --output "$WORK/合并.ofd" --json >/dev/null 2>&1 \
  && "${KIT[@]}" ofd info --input "$WORK/合并.ofd" --json 2>/dev/null | grep -q '"pages": *4' \
  && ok "ofd merge（2+2=4 页）" || bad "ofd merge"

step "4. pdf：Stirling 后端 + 常用工具"
"${KIT[@]}" pdf start --json >"$WORK/pstart.json" 2>"$WORK/pstart.err" \
  && ok "pdf start（首次可能 60-100s）" || { bad "pdf start"; tail -5 "$WORK/pstart.err"; }
"${KIT[@]}" pdf status --json >"$WORK/pstatus.json" 2>/dev/null && grep -q '"ready": *true' "$WORK/pstatus.json" \
  && ok "pdf status ready" || bad "pdf status ready"
"${KIT[@]}" pdf run merge --input "$WORK/报告.pdf" --input "$WORK/样例.pdf" --output "$WORK/合并.pdf" --json >"$WORK/pmerge.json" 2>"$WORK/pmerge.err" \
  && need "$WORK/合并.pdf" && ok "pdf merge" || { bad "pdf merge"; tail -3 "$WORK/pmerge.err"; }
"${KIT[@]}" pdf run extract-text --input "$WORK/合并.pdf" --output "$WORK/合并.txt" --json >/dev/null 2>&1 \
  && grep -q "离线" "$WORK/合并.txt" && ok "pdf extract-text" || bad "pdf extract-text"
"${KIT[@]}" pdf run pdf-to-img --input "$WORK/报告.pdf" --output-dir "$WORK/pdf-png" --json >/dev/null 2>&1 \
  && ls "$WORK/pdf-png"/* >/dev/null 2>&1 && ok "pdf -> img" || bad "pdf -> img"
"${KIT[@]}" pdf run split --input "$WORK/合并.pdf" --option pageNumbers=all --output-dir "$WORK/split" --json >/dev/null 2>&1 \
  && ls "$WORK/split"/*.pdf >/dev/null 2>&1 && ok "pdf split" || bad "pdf split"
"${KIT[@]}" pdf run encrypt --input "$WORK/报告.pdf" --output "$WORK/报告-加密.pdf" --option password=test123 --json >/dev/null 2>&1 \
  && need "$WORK/报告-加密.pdf" && ok "pdf encrypt" || bad "pdf encrypt"
"${KIT[@]}" pdf run decrypt --input "$WORK/报告-加密.pdf" --output "$WORK/报告-解密.pdf" --option password=test123 --json >/dev/null 2>&1 \
  && need "$WORK/报告-解密.pdf" && ok "pdf decrypt" || bad "pdf decrypt"

step "5. asr：语音转文字 / SRT"
if ffmpeg -hide_banner -loglevel error -y -f lavfi -i "flite=text='this is an offline integration test for speech recognition':voice=slt" -ar 16000 -ac 1 "$WORK/speech.wav" 2>/dev/null; then
  ok "合成测试语音"
else
  ffmpeg -hide_banner -loglevel error -y -f lavfi -i "sine=frequency=440:duration=1" -ar 16000 -ac 1 "$WORK/speech.wav"
  ok "合成静音测试音频（无 flite）"
fi
"${KIT[@]}" asr file --input "$WORK/speech.wav" --format json --json >"$WORK/asr.json" 2>"$WORK/asr.err" \
  && "$PY" - "$WORK/asr.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
assert d["segments"] is not None
assert isinstance(d["text"], str)
assert d["engine"].startswith("sensevoice")
PY
ok "asr file json" || { bad "asr file json"; tail -3 "$WORK/asr.err"; }
"${KIT[@]}" asr file --input "$WORK/speech.wav" --format srt >"$WORK/asr.srt" 2>/dev/null \
  && grep -q -- "-->" "$WORK/asr.srt" && ok "asr srt" || bad "asr srt"

step "6. 断网语义（代理指向黑洞）复测关键路径"
export http_proxy="http://127.0.0.1:9" https_proxy="http://127.0.0.1:9" all_proxy="http://127.0.0.1:9"
export HTTP_PROXY="$http_proxy" HTTPS_PROXY="$https_proxy" ALL_PROXY="$all_proxy"
"${KIT[@]}" ocr image --input "$WORK/ppt-png/page-001.png" --json >/dev/null 2>&1 \
  && ok "断网 ocr" || bad "断网 ocr"
"${KIT[@]}" asr file --input "$WORK/speech.wav" --json >/dev/null 2>&1 \
  && ok "断网 asr" || bad "断网 asr"
"${KIT[@]}" office convert --input "$WORK/报告 中文.docx" --output "$WORK/断网.pdf" --json >/dev/null 2>&1 \
  && ok "断网 office convert" || bad "断网 office convert"
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

step "7. 清理"
"${KIT[@]}" pdf stop --json >/dev/null 2>&1 && ok "pdf stop"

printf '\n通过 %d 项，失败 %d 项\n' "$pass" "$fail"
if [ "$fail" -ne 0 ]; then
  echo "集成验收失败" >&2
  exit 1
fi
echo "PASS"
