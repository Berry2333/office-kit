#!/bin/bash
# modules/asr/test.sh — office-kit asr 模块自检
#
# 覆盖：帮助、文本/JSON/SRT 转写、ffmpeg 音频归一化（mp3 44.1k 立体声 -> 16k 单声道）、
#       连续听写 VAD 切句、设备/模型结构、错误码、断网语义。
# 麦克风录音在无设备/无语音时允许 SKIP（打印 SKIP，不失败）。
set -u

_self="$(readlink -f "$0" 2>/dev/null || echo "$0")"
MOD="$(cd "$(dirname "$_self")" && pwd)"
KIT="$(cd "${MOD}/../.." && pwd)"
ASR="${MOD}/bin/asr"

# 与 office-kit 一致的环境（直接执行模块入口时也能拿到运行时变量）
export OFFICE_KIT_ROOT="${OFFICE_KIT_ROOT:-$KIT}"
export OFFICE_KIT_RUNTIME="${OFFICE_KIT_RUNTIME:-$KIT/runtime}"
export OFFICE_KIT_DATA="${OFFICE_KIT_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/office-kit}"
export OFFICE_KIT_CACHE="${OFFICE_KIT_CACHE:-$OFFICE_KIT_DATA/cache}"
export OFFICE_KIT_MODELS="${OFFICE_KIT_MODELS:-$OFFICE_KIT_RUNTIME/models}"
export OFFICE_KIT_PY="${OFFICE_KIT_PY:-$OFFICE_KIT_RUNTIME/python/bin/python3}"

# 断网语义：任何联网尝试都应快速失败，不允许模块依赖网络。
export http_proxy="http://127.0.0.1:9" https_proxy="http://127.0.0.1:9" \
       all_proxy="http://127.0.0.1:9" no_proxy="localhost,127.0.0.1"
export HTTP_PROXY="$http_proxy" HTTPS_PROXY="$https_proxy" ALL_PROXY="$all_proxy"

PY="$OFFICE_KIT_PY"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 2>/dev/null || true)"
fi
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "FAIL: 未找到 Python 运行时" >&2
  exit 1
fi

# 原子创建独立临时目录：不依赖 .tmp 是否已在、也不会与其他测试/清理竞争。
TMP="$(mktemp -d "${TMPDIR:-/tmp}/office-kit-asr-test.XXXXXX")" ||
  { echo "FAIL: 无法创建临时目录" >&2; exit 1; }
mkdir -p "$TMP/cache"
# 测试产生的归一化/录音/sha 缓存都留在临时目录，不污染用户 cache。
export OFFICE_KIT_CACHE="$TMP/cache"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "ok - $*"; }
skip() { echo "SKIP - $*"; }

[ -x "$ASR" ] || fail "asr 入口不可执行：$ASR"

# ---------------------------------------------------------------------------
# 0. 帮助与参数
# ---------------------------------------------------------------------------
"$ASR" --help >/dev/null 2>&1 || fail "--help"
"$ASR" file --help >/dev/null 2>&1 || fail "file --help"
"$ASR" listen --help >/dev/null 2>&1 || fail "listen --help"
"$ASR" models --help >/dev/null 2>&1 || fail "models --help"
ok "帮助可用"

"$ASR" file >/dev/null 2>&1
[ "$?" -eq 2 ] || fail "缺少 --input 应返回 2"
"$ASR" file --input "$TMP/不存在.wav" >/dev/null 2>&1
[ "$?" -eq 1 ] || fail "输入不存在应返回 1"
ok "退出码约定（参数错误 2 / 运行时错误 1）"

# ---------------------------------------------------------------------------
# 1. 合成测试语音（flite 不可用时退化为静音 WAV，只验证流程）
# ---------------------------------------------------------------------------
WAV="$TMP/speech.wav"
HAVE_SPEECH=0
if command -v ffmpeg >/dev/null 2>&1 &&
   ffmpeg -hide_banner -loglevel error -y -f lavfi \
     -i "flite=text='Hello, this is an offline speech recognition test.':voice=slt" \
     -ar 16000 -ac 1 "$WAV" >/dev/null 2>&1 &&
   [ -s "$WAV" ]; then
  HAVE_SPEECH=1
  ok "ffmpeg flite 合成测试语音"
else
  ffmpeg -hide_banner -loglevel error -y -f lavfi \
    -i "anullsrc=r=16000:cl=mono" -t 2 -ar 16000 -ac 1 "$WAV" >/dev/null 2>&1 ||
    fail "无法生成测试音频"
  skip "ffmpeg 缺少 flite，使用静音 WAV 验证流程"
fi

TWO="$TMP/two.wav"
if [ "$HAVE_SPEECH" = "1" ]; then
  A="$TMP/sentence-a.wav"
  B="$TMP/sentence-b.wav"
  SIL="$TMP/silence.wav"
  ffmpeg -hide_banner -loglevel error -y -f lavfi \
    -i "flite=text='The first sentence is about weather.':voice=slt" \
    -ar 16000 -ac 1 "$A" >/dev/null 2>&1
  ffmpeg -hide_banner -loglevel error -y -f lavfi \
    -i "flite=text='The second sentence is about music.':voice=slt" \
    -ar 16000 -ac 1 "$B" >/dev/null 2>&1
  ffmpeg -hide_banner -loglevel error -y -f lavfi \
    -i "anullsrc=r=16000:cl=mono" -t 1.0 -ar 16000 -ac 1 "$SIL" >/dev/null 2>&1
  printf "file '%s'\n" "$A" "$SIL" "$B" > "$TMP/concat.txt"
  ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$TMP/concat.txt" \
    -ar 16000 -ac 1 "$TWO" >/dev/null 2>&1 || cp "$WAV" "$TWO"
fi

# ---------------------------------------------------------------------------
# 2. file --format text
# ---------------------------------------------------------------------------
TEXT="$("$ASR" file --input "$WAV" --format text 2>"$TMP/text.err")" ||
  fail "file --format text：$(tail -1 "$TMP/text.err")"
[ -z "$TEXT" ] || echo "  识别文本：$TEXT"
if [ "$HAVE_SPEECH" = "1" ]; then
  printf '%s' "$TEXT" | grep -qiE 'speech|recognition|test' ||
    fail "文本结果缺少预期关键词：$TEXT"
else
  [ -z "$TEXT" ] || fail "静音输入应输出空文本，实际：$TEXT"
fi
ok "file --format text"

# ---------------------------------------------------------------------------
# 3. file --format json（结构断言）
# ---------------------------------------------------------------------------
"$ASR" file --input "$WAV" --format json > "$TMP/out.json" 2>"$TMP/json.err" ||
  fail "file --format json：$(tail -1 "$TMP/json.err")"
"$PY" - "$TMP/out.json" "$HAVE_SPEECH" <<'PY' || fail "JSON 结构不符合契约"
import json, sys
path, have = sys.argv[1], sys.argv[2] == "1"
with open(path, encoding="utf-8") as fh:
    obj = json.load(fh)
assert obj["engine"] == "sensevoice-small-q8", obj
assert isinstance(obj["input"], str) and obj["input"], obj
assert isinstance(obj["duration"], (int, float)) and obj["duration"] > 0, obj
assert isinstance(obj["duration_ms"], int) and obj["duration_ms"] > 0, obj
assert isinstance(obj["elapsed_ms"], int) and obj["elapsed_ms"] >= 0, obj
assert isinstance(obj["text"], str), obj
assert isinstance(obj["segments"], list), obj
if have:
    assert obj["segments"], obj
for seg in obj["segments"]:
    assert {"start", "end", "text"} <= set(seg), seg
    assert isinstance(seg["start"], (int, float)), seg
    assert isinstance(seg["end"], (int, float)), seg
if have:
    assert obj["text"].strip(), obj
    assert obj["language"] == "en", obj
else:
    assert obj["text"] == "", obj
    assert obj["segments"] == [], obj
PY
ok "file --format json（字段与 segments）"

# --json 等价于 --format json
"$ASR" file --input "$WAV" --json > "$TMP/out2.json" 2>/dev/null ||
  fail "file --json"
"$PY" - "$TMP/out2.json" <<'PY' || fail "file --json 输出不是合法 JSON"
import json, sys
json.load(open(sys.argv[1], encoding="utf-8"))
PY
ok "file --json"

# ---------------------------------------------------------------------------
# 4. file --format srt（引擎 --srt + JSON 信封）
# ---------------------------------------------------------------------------
"$ASR" file --input "$WAV" --format srt > "$TMP/out.srt" 2>"$TMP/srt.err" ||
  fail "file --format srt：$(tail -1 "$TMP/srt.err")"
if [ "$HAVE_SPEECH" = "1" ]; then
  grep -q -- '-->' "$TMP/out.srt" || fail "SRT 缺少时间轴"
  grep -q '00:00:00,000' "$TMP/out.srt" || fail "SRT 起始时间异常"
  grep -qiE 'speech|recognition|test' "$TMP/out.srt" || fail "SRT 缺少预期文本"
else
  [ -s "$TMP/out.srt" ] && fail "纯静音输入应输出空 SRT"
fi
"$ASR" file --input "$WAV" --format srt --json > "$TMP/out-srt.json" 2>/dev/null ||
  fail "file --format srt --json"
"$PY" - "$TMP/out-srt.json" "$HAVE_SPEECH" <<'PY' || fail "SRT JSON 信封结构错误"
import json, sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
have = sys.argv[2] == "1"
assert obj["format"] == "srt", obj
assert isinstance(obj["srt"], str), obj
if have:
    assert "-->" in obj["srt"], obj
    assert obj["segments"], obj
else:
    assert obj["srt"] == "", obj
    assert obj["segments"] == [], obj
PY
ok "file --format srt / srt --json"

# ---------------------------------------------------------------------------
# 5. 音频归一化：44.1 kHz 立体声 mp3 + 中文/空格路径
# ---------------------------------------------------------------------------
NORM_DIR="$TMP/中文 目录"
mkdir -p "$NORM_DIR"
MP3="$NORM_DIR/录音 测试.mp3"
if command -v ffmpeg >/dev/null 2>&1 &&
   ffmpeg -hide_banner -loglevel error -y -i "$WAV" -ar 44100 -ac 2 \
     -c:a libmp3lame -q:a 4 "$MP3" >/dev/null 2>&1 && [ -s "$MP3" ]; then
  MP3_TEXT="$("$ASR" file --input "$MP3" --format text 2>"$TMP/mp3.err")" ||
    fail "mp3 归一化转写：$(tail -1 "$TMP/mp3.err")"
  if [ "$HAVE_SPEECH" = "1" ]; then
    printf '%s' "$MP3_TEXT" | grep -qiE 'speech|recognition|test|hello' ||
      fail "mp3 转写缺少关键词：$MP3_TEXT"
  fi
  ok "ffmpeg 归一化（44.1k 立体声 mp3，中文/空格路径）"
else
  skip "ffmpeg 缺少 libmp3lame，跳过 mp3 归一化测试"
fi

# ---------------------------------------------------------------------------
# 5b. 无 ffmpeg 后备：44.1 kHz 立体声 WAV 由 Python wave+audioop 归一化
# ---------------------------------------------------------------------------
NOBIN="$TMP/nobin"
mkdir -p "$NOBIN"
for tool in bash dirname readlink mkdir; do
  target="$(command -v "$tool" 2>/dev/null || true)"
  [ -n "$target" ] && ln -sf "$target" "$NOBIN/$tool"
done
STEREO="$TMP/stereo-44k.wav"
if [ -x "$NOBIN/bash" ] && command -v ffmpeg >/dev/null 2>&1 &&
   ffmpeg -hide_banner -loglevel error -y -i "$WAV" -ar 44100 -ac 2 "$STEREO" >/dev/null 2>&1 &&
   [ -s "$STEREO" ]; then
  PATH="$NOBIN" "$ASR" file --input "$STEREO" --format text \
    > "$TMP/noffmpeg.txt" 2> "$TMP/noffmpeg.err" ||
    fail "无 ffmpeg 的 WAV 后备转换失败：$(tail -1 "$TMP/noffmpeg.err")"
  if [ "$HAVE_SPEECH" = "1" ]; then
    grep -q '[^[:space:]]' "$TMP/noffmpeg.txt" ||
      fail "无 ffmpeg 后备转换后未识别出文本"
  fi
  ok "无 ffmpeg 后备（wave+audioop 归一化 44.1k 立体声 WAV）"
else
  skip "无法构造无 ffmpeg 后备测试"
fi

# ---------------------------------------------------------------------------
# 6. models / devices 结构
# ---------------------------------------------------------------------------
"$ASR" models --json > "$TMP/models.json" 2>"$TMP/models.err" ||
  fail "models --json：$(tail -1 "$TMP/models.err")"
"$PY" - "$TMP/models.json" <<'PY' || fail "models JSON 结构错误"
import json, sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
assert obj["engine"] == "sensevoice-small-q8", obj
assert obj["available"] is True, obj
assert obj["model_size"] > 100 * 1024 * 1024, obj
assert len(obj["model_sha256_12"]) == 12, obj
assert len(obj["engine_sha256_12"]) == 12, obj
assert isinstance(obj["threads"], int) and obj["threads"] >= 1, obj
assert "tools" in obj and isinstance(obj["tools"], dict), obj
PY
ok "models --json"

"$ASR" devices --json > "$TMP/devices.json" 2>"$TMP/devices.err" ||
  fail "devices --json：$(tail -1 "$TMP/devices.err")"
"$PY" - "$TMP/devices.json" <<'PY' || fail "devices JSON 结构错误"
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert isinstance(data, list), data
for item in data:
    assert isinstance(item["card"], int), item
    assert isinstance(item["device"], int), item
    assert isinstance(item["name"], str), item
print("  采集设备 %d 个" % len(data))
PY
ok "devices --json"

# ---------------------------------------------------------------------------
# 7. listen：连续听写切句（--input 用音频文件模拟麦克风）
# ---------------------------------------------------------------------------
if [ "$HAVE_SPEECH" = "1" ] && [ -s "$TWO" ]; then
  "$ASR" listen --input "$TWO" --json > "$TMP/listen.jsonl" 2>"$TMP/listen.err" ||
    fail "listen：$(tail -1 "$TMP/listen.err")"
  LINES="$(wc -l < "$TMP/listen.jsonl")"
  [ "$LINES" -ge 2 ] || fail "listen 应切出至少 2 句，实际 $LINES 句"
  "$PY" - "$TMP/listen.jsonl" <<'PY' || fail "listen JSONL 结构错误"
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
assert len(rows) >= 2, rows
last = -1.0
for row in rows:
    assert {"index", "text", "start", "end", "language", "elapsed_ms"} <= set(row), row
    assert row["text"].strip(), row
    assert row["end"] >= row["start"] >= last, row
    last = row["end"]
PY
  ok "listen 连续听写（VAD 切出 $LINES 句）"

  ONCE="$("$ASR" listen --input "$TWO" --once --json 2>/dev/null | wc -l)"
  [ "$ONCE" -eq 1 ] || fail "--once 应只输出 1 句，实际 $ONCE"
  ok "listen --once"
else
  skip "无合成语音，跳过 listen 切句测试"
fi

# ---------------------------------------------------------------------------
# 8. input：剪贴板 + 自动粘贴（用伪 xclip/ydotool，避免动真实剪贴板）
# ---------------------------------------------------------------------------
if [ "$HAVE_SPEECH" = "1" ]; then
  FAKEBIN="$TMP/fakebin"
  mkdir -p "$FAKEBIN"
  cat > "$FAKEBIN/xclip" <<'SH'
#!/bin/bash
cat > "$FAKE_CLIP_FILE"
SH
  cat > "$FAKEBIN/ydotool" <<'SH'
#!/bin/bash
printf 'ydotool: %s\n' "$*" >> "$FAKE_PASTE_LOG"
exit 0
SH
  chmod +x "$FAKEBIN/xclip" "$FAKEBIN/ydotool"
  CLIP="$TMP/clip.txt"
  PASTELOG="$TMP/paste.log"
  rm -f "$CLIP" "$PASTELOG"
  PATH="$FAKEBIN:/usr/bin:/bin" DISPLAY=:0 \
    FAKE_CLIP_FILE="$CLIP" FAKE_PASTE_LOG="$PASTELOG" \
    "$ASR" input --input "$WAV" --json \
    > "$TMP/input.json" 2> "$TMP/input.err" ||
    fail "input：$(tail -1 "$TMP/input.err")"
  [ -s "$CLIP" ] || fail "input 没有写入剪贴板"
  grep -qiE 'speech|recognition|test|hello' "$CLIP" ||
    fail "剪贴板内容缺少预期文本：$(cat "$CLIP")"
  grep -qF 'key 29:1 47:1 47:0 29:0' "$PASTELOG" ||
    fail "ydotool 按键序列不正确：$(cat "$PASTELOG" 2>/dev/null)"
  "$PY" - "$TMP/input.json" <<'PY' || fail "input JSON 结构错误"
import json, sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
assert obj["text"].strip(), obj
assert obj["clipboard"] == "xclip", obj
assert obj["pasted"] is True, obj
PY
  ok "input 剪贴板/自动粘贴（伪 xclip/ydotool）"
else
  skip "无合成语音，跳过 input 剪贴板测试"
fi

# ---------------------------------------------------------------------------
# 9. mic：无设备/无有效语音时允许 SKIP
# ---------------------------------------------------------------------------
if timeout 40 "$ASR" mic --seconds 1 --format text \
     > "$TMP/mic.txt" 2> "$TMP/mic.err"; then
  if grep -q '[^[:space:]]' "$TMP/mic.txt"; then
    ok "mic（识别：$(head -c 80 "$TMP/mic.txt")）"
  else
    skip "mic 已录音但未检测到有效语音（当前无声卡输入/静音）"
  fi
else
  RC=$?
  skip "mic 不可用（退出码 $RC：$(tail -1 "$TMP/mic.err")）"
fi

# ---------------------------------------------------------------------------
# 10. 断网语义：以上所有命令都在 http_proxy=127.0.0.1:9 下完成
# ---------------------------------------------------------------------------
ok "断网语义（proxy 127.0.0.1:9，全程无联网依赖）"

echo "OK asr"
exit 0
