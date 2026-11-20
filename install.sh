#!/bin/bash
# office-kit 安装脚本：安装 AppImage + 把 5 个技能装进 DSH 技能目录（全程离线可用）
#
#   ./install.sh                 # 默认 ~/apps + ${DSH_HOME:-$HOME/.dsh}/skills
#   ./install.sh --prefix DIR    # 自定义 AppImage 安装目录
#   ./install.sh --dsh-home DIR  # 自定义 DSH_HOME
#   ./install.sh --skills-only   # 只装技能（AppImage 已手动放好）
#   ./install.sh --uninstall     # 卸载技能与 shim（保留 AppImage）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-$HOME/apps}"
DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
SKILLS_ONLY=0
UNINSTALL=0
APPIMAGE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --dsh-home) DSH_HOME="$2"; shift 2 ;;
    --appimage) APPIMAGE="$2"; shift 2 ;;
    --skills-only) SKILLS_ONLY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

SKILL_NAMES="office-docs pdf-tools ofd-tools ocr-tools asr-voice"
BIN_DIR="$HOME/.local/bin"
SHIM="$BIN_DIR/office-kit"

if [ "$UNINSTALL" = 1 ]; then
  exec "${ROOT}/uninstall.sh" --prefix "$PREFIX" --dsh-home "$DSH_HOME" "$@"
fi

# ---- 1. AppImage ----
if [ "$SKILLS_ONLY" = 0 ]; then
  mkdir -p "$PREFIX"
  if [ -n "$APPIMAGE" ]; then
    SRC="$APPIMAGE"
  else
    SRC="$(ls -1 "$ROOT"/dist/office-kit-*-linux-arm64.AppImage 2>/dev/null | tail -1 || true)"
  fi
  [ -n "${SRC:-}" ] && [ -f "$SRC" ] || { echo "找不到 AppImage；先运行 build/build-appimage.sh，或用 --appimage 指定" >&2; exit 1; }
  DEST="$PREFIX/office-kit.AppImage"
  echo "安装 AppImage: $DEST"
  cp -f "$SRC" "$DEST"
  chmod +x "$DEST"
  mkdir -p "$BIN_DIR"
  cat > "$SHIM" <<SHIMEOF
#!/bin/bash
exec "$DEST" "\$@"
SHIMEOF
  chmod +x "$SHIM"
  echo "已创建命令: $SHIM"
  "$DEST" --version
fi

# ---- 2. 技能 ----
mkdir -p "$DSH_HOME/skills"
for s in $SKILL_NAMES; do
  if [ -d "$ROOT/skills/$s" ]; then
    rm -rf "$DSH_HOME/skills/$s"
    cp -a "$ROOT/skills/$s" "$DSH_HOME/skills/$s"
    echo "已安装技能: $s -> $DSH_HOME/skills/$s"
  else
    echo "警告: 缺少 skills/$s，跳过" >&2
  fi
done

cat <<EOF

完成。DSH 重启或新会话后即可看到技能：
  office-docs  Word/Excel/PPT 创建、转 PDF、渲染、公式重算
  pdf-tools    PDF 合并/拆分/加密/水印/抽文本/转图/OCR
  ofd-tools    OFD 读取、转 PDF/图片/文本/HTML、合并
  ocr-tools    图片/扫描件 OCR（带坐标 JSON）
  asr-voice    语音转写、SRT、麦克风听写、语音输入

命令行自检：
  office-kit --version
  office-kit list
  office-kit office --help
EOF
