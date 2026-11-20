#!/bin/bash
# office-kit 卸载脚本
#
#   ./uninstall.sh                 # 停止后端 + 删除技能/shim/AppImage（保留缓存与数据）
#   ./uninstall.sh --purge         # 连同 ~/.local/share/office-kit 数据目录一起删除
#   ./uninstall.sh --keep-appimage # 只删技能与 shim，保留 AppImage
#   ./uninstall.sh --dry-run       # 只打印将删除的内容，不动手
#   ./uninstall.sh --yes           # 不交互确认
#
# 可用 --prefix/--dsh-home 指定非默认安装位置（与 install.sh 保持一致）。
set -euo pipefail

PREFIX="${PREFIX:-$HOME/apps}"
DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
DATA="${OFFICE_KIT_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/office-kit}"
SHIM="$HOME/.local/bin/office-kit"
APPIMAGE="$PREFIX/office-kit.AppImage"
SKILL_NAMES="office-docs pdf-tools ofd-tools ocr-tools asr-voice"

PURGE=0
KEEP_APPIMAGE=0
DRY=0
YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; APPIMAGE="$PREFIX/office-kit.AppImage"; shift 2 ;;
    --dsh-home) DSH_HOME="$2"; shift 2 ;;
    --purge) PURGE=1; shift ;;
    --keep-appimage) KEEP_APPIMAGE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

run() {
  if [ "$DRY" = 1 ]; then
    printf '  [dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

note() { printf '\033[1;36m%s\033[0m\n' "$*"; }

# 安全检查：所有删除目标必须是绝对路径且不在根/家目录本身
guard() {
  case "$1" in
    ""|"/"|"$HOME"|"$HOME/"|"/home"|"/usr"|"/opt"|"/etc")
      echo "拒绝删除危险路径：$1" >&2; exit 1 ;;
  esac
  case "$1" in
    /*) ;;
    *) echo "拒绝删除非绝对路径：$1" >&2; exit 1 ;;
  esac
}

note "将要卸载 office-kit"
printf '  AppImage : %s\n' "$APPIMAGE"
printf '  命令入口 : %s\n' "$SHIM"
printf '  技能目录 : %s/skills/{%s}\n' "$DSH_HOME" "$(echo "$SKILL_NAMES" | tr ' ' ',')"
printf '  数据目录 : %s%s\n' "$DATA" "$([ "$PURGE" = 1 ] && echo '（--purge 将删除）' || echo '（保留）')"
echo

if [ "$DRY" = 0 ] && [ "$YES" = 0 ]; then
  read -r -p "确认卸载？[y/N] " reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "已取消"; exit 0 ;;
  esac
fi

note "1/5 停止 PDF 后端"
if [ -x "$SHIM" ]; then
  run "$SHIM" pdf stop >/dev/null 2>&1 || true
elif [ -x "$APPIMAGE" ]; then
  run "$APPIMAGE" pdf stop >/dev/null 2>&1 || true
fi
# 兜底：只杀本工具数据目录下启动的 Stirling（不碰其它 Java 进程）
if [ "$DRY" = 0 ] && [ -d "$DATA/pdf" ]; then
  for pid in $(ps -eo pid=,args= | grep -F -- "-Dlogging.file.path=$DATA/pdf/logs" | grep -v grep | awk '{print $1}'); do
    kill "$pid" 2>/dev/null || true
  done
fi

note "2/5 删除命令入口"
if [ -e "$SHIM" ] || [ -L "$SHIM" ]; then
  guard "$SHIM"
  run rm -f "$SHIM"
else
  echo "  未找到 $SHIM（跳过）"
fi

note "3/5 删除 AppImage"
if [ "$KEEP_APPIMAGE" = 1 ]; then
  echo "  --keep-appimage：保留 $APPIMAGE"
elif [ -f "$APPIMAGE" ]; then
  guard "$APPIMAGE"
  run rm -f "$APPIMAGE"
else
  echo "  未找到 $APPIMAGE（跳过）"
fi

note "4/5 移除 DSH 技能"
for s in $SKILL_NAMES; do
  d="$DSH_HOME/skills/$s"
  if [ -d "$d" ]; then
    guard "$d"
    run rm -rf "$d"
    [ "$DRY" = 1 ] || echo "  已移除 $s"
  fi
done

note "5/5 数据目录"
if [ "$PURGE" = 1 ]; then
  if [ -d "$DATA" ]; then
    guard "$DATA"
    run rm -rf "$DATA"
    echo "  已删除 $DATA"
  else
    echo "  未找到 $DATA（跳过）"
  fi
else
  echo "  保留 $DATA（含 PDF 解包与缓存）；需要彻底清理请加 --purge"
fi

echo
if [ "$DRY" = 1 ]; then
  echo "dry-run 结束：没有删除任何文件。"
else
  echo "卸载完成。如需重装：./install.sh"
fi
