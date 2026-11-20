#!/bin/bash
# 构建 office-kit AppImage（aarch64）
#
# 产物: dist/office-kit-<版本>-linux-arm64.AppImage
# 用法: bash build/build-appimage.sh [--no-compress]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${VERSION:-1.0.0}"
NAME="office-kit"
BUILD="$ROOT/build/appdir"
DIST="$ROOT/dist"
APPDIR="$BUILD/${NAME}.AppDir"
TOOL="${APPIMAGETOOL:-/home/link/桌面/code/stirling-desktop-build/downloads/appimagetool-aarch64.AppImage}"
RUNTIME="${APPIMAGE_RUNTIME:-/home/link/桌面/code/stirling-desktop-build/downloads/runtime-aarch64}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m错误: %s\033[0m\n' "$*" >&2; exit 1; }

[ -x "$ROOT/bin/office-kit" ] || die "缺少 bin/office-kit"
[ -d "$ROOT/runtime/jre" ] || die "runtime 未就位"
[ -d "$ROOT/modules" ] || die "缺少 modules/"

step "清理旧的 AppDir"
rm -rf "$APPDIR" "$DIST"
mkdir -p "$APPDIR/usr/share" "$APPDIR/usr/bin" "$DIST"

step "复制内容（runtime / modules / bin / skills / docs）"
mkdir -p "$APPDIR/usr/share/office-kit"
for part in bin modules runtime skills docs test README.md AGENTS-CONTRACT.md install.sh uninstall.sh; do
  [ -e "$ROOT/$part" ] || continue
  cp -a "$ROOT/$part" "$APPDIR/usr/share/office-kit/"
done
# 去掉开发期残留
find "$APPDIR/usr/share/office-kit" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$APPDIR/usr/share/office-kit" -name '*.pyc' -delete 2>/dev/null || true
rm -rf "$APPDIR/usr/share/office-kit/modules"/*/.build 2>/dev/null || true

step "写入 AppRun / desktop / 图标"
ln -sf usr/share/office-kit/bin/office-kit "$APPDIR/usr/bin/office-kit" 2>/dev/null || true
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/bash
set -u
HERE="$(dirname "$(readlink -f "$0")")"
export OFFICE_KIT_ROOT="$HERE/usr/share/office-kit"
export OFFICE_KIT_DATA="${OFFICE_KIT_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/office-kit}"
unset ELECTRON_RUN_AS_NODE
export PATH="$OFFICE_KIT_ROOT/bin:$PATH"
if [ "$#" -eq 0 ]; then
  exec "$OFFICE_KIT_ROOT/bin/office-kit" --help
fi
exec "$OFFICE_KIT_ROOT/bin/office-kit" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/${NAME}.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=office-kit 离线办公工具箱
Name[en]=office-kit Offline Office Toolkit
Comment=Word/Excel/PPT、PDF、OFD、OCR、语音识别，完全离线
Exec=office-kit
Icon=office-kit
Terminal=true
Categories=Office;Utility;
DESKTOP

if [ -f "$ROOT/build/office-kit.png" ]; then
  cp "$ROOT/build/office-kit.png" "$APPDIR/office-kit.png"
else
  cp "$APPDIR/usr/share/office-kit/bin/office-kit" /dev/null 2>/dev/null || true
fi
ln -sf office-kit.png "$APPDIR/.DirIcon" 2>/dev/null || true

step "体积统计"
du -sh "$APPDIR" "$APPDIR/usr/share/office-kit"/* 2>/dev/null | sort -h | tail -8

step "打包 AppImage（zstd）"
[ -x "$TOOL" ] || die "找不到 appimagetool: $TOOL（用 APPIMAGETOOL= 指定）"
STAGE_RT="$(mktemp -d)/runtime"
cp "$RUNTIME" "$STAGE_RT"
ARCH=aarch64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" -n --comp zstd \
  --runtime-file "$STAGE_RT" \
  "$APPDIR" "$DIST/${NAME}-${VERSION}-linux-arm64.AppImage"

step "收尾"
cd "$DIST"
sha256sum "${NAME}-${VERSION}-linux-arm64.AppImage" > "${NAME}-${VERSION}-linux-arm64.AppImage.sha256"
ls -lh
printf '\n完成: %s\n' "$DIST/${NAME}-${VERSION}-linux-arm64.AppImage"
