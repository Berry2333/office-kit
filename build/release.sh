#!/bin/bash
# 一键发布：跑模块自检 → 清理 → 打 AppImage → 冒烟测试 → 生成校验与说明
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${VERSION:-1.0.0}"
DIST="$ROOT/dist"
APPIMAGE="$DIST/office-kit-${VERSION}-linux-arm64.AppImage"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m错误: %s\033[0m\n' "$*" >&2; exit 1; }

step "1/5 模块自检"
for m in office pdf ofd ocr asr; do
  if [ -f "$ROOT/modules/$m/test.sh" ]; then
    printf '\n--- %s ---\n' "$m"
    bash "$ROOT/modules/$m/test.sh" || die "模块 $m 自检失败"
  else
    die "缺少 modules/$m/test.sh"
  fi
done

step "2/5 清理构建残留"
find "$ROOT/modules" "$ROOT/skills" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$ROOT/modules" "$ROOT/skills" -name '*.pyc' -delete 2>/dev/null || true
rm -rf "$ROOT/.tmp"

step "3/5 打包 AppImage"
VERSION="$VERSION" bash "$ROOT/build/build-appimage.sh"

step "4/5 冒烟测试（AppImage 实跑）"
[ -f "$APPIMAGE" ] || die "未生成 $APPIMAGE"
export APPIMAGE_EXTRACT_AND_RUN=1
"$APPIMAGE" --version
"$APPIMAGE" list
"$APPIMAGE" office --help >/dev/null
"$APPIMAGE" pdf --help >/dev/null
"$APPIMAGE" ofd --help >/dev/null
"$APPIMAGE" ocr --help >/dev/null
"$APPIMAGE" asr --help >/dev/null
echo "CLI 冒烟通过"

step "5/5 生成发布说明"
cat > "$DIST/RELEASE-${VERSION}.md" <<EOF
# office-kit ${VERSION}

- AppImage: office-kit-${VERSION}-linux-arm64.AppImage
- 技能: office-docs / pdf-tools / ofd-tools / ocr-tools / asr-voice
- 构建时间: $(date '+%Y-%m-%d %H:%M:%S %Z')
- 校验: $(cat "$APPIMAGE.sha256" 2>/dev/null || sha256sum "$APPIMAGE")
EOF
ls -lh "$DIST"
printf '\n发布完成: %s\n' "$APPIMAGE"
