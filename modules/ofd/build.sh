#!/bin/bash
# 构建 modules/ofd（构建期联网；运行期完全离线）
#
# 产物:
#   modules/ofd/lib/classes/ofdkit/*.class   本模块 Java 类
#   modules/ofd/lib/jars/*.jar               全部运行时依赖（ofdrw + PDFBox + Batik ...）
#
# 依赖（仅构建期，放在 .tmp/ofd/，不入库）:
#   .tmp/ofd/jdk     Temurin JDK 21（提供 javac；运行时仍用 runtime/jre）
#   .tmp/ofd/maven   Apache Maven 3.9.16
#   .tmp/ofd/m2      Maven 本地仓库缓存
#
# 可用环境变量覆盖: OFD_JDK / OFD_MVN / OFD_M2 / OFD_NO_DOWNLOAD=1
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_ROOT="$(cd "${MODULE_DIR}/../.." && pwd)"
TMP_ROOT="${KIT_ROOT}/.tmp/ofd"

JDK="${OFD_JDK:-${TMP_ROOT}/jdk}"
MVN="${OFD_MVN:-${TMP_ROOT}/maven/bin/mvn}"
M2="${OFD_M2:-${TMP_ROOT}/m2}"

JDK_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jdk_aarch64_linux_hotspot_21.0.13_9.tar.gz"
MVN_URL="https://dlcdn.apache.org/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.tar.gz"
MVN_URL_FALLBACK="https://archive.apache.org/dist/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.tar.gz"

log() { printf '[ofd-build] %s\n' "$*"; }
die() { printf '[ofd-build] 错误: %s\n' "$*" >&2; exit 3; }

mkdir -p "${TMP_ROOT}"

download() {
  # download <url> <output>
  local url="$1" out="$2"
  log "下载 ${url}"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --connect-timeout 30 -o "${out}" "${url}"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${out}" "${url}"
  else
    die "需要 curl 或 wget 下载构建依赖"
  fi
}

# ---------------------------------------------------------------------------
# 1. JDK（只需 javac；运行期用 runtime/jre）
# ---------------------------------------------------------------------------
if [ ! -x "${JDK}/bin/javac" ]; then
  [ "${OFD_NO_DOWNLOAD:-0}" = "1" ] && die "缺少 JDK: ${JDK}/bin/javac（OFD_NO_DOWNLOAD=1 禁止下载）"
  log "未找到 JDK，开始下载 Temurin 21（约 206MB）..."
  rm -rf "${TMP_ROOT}/jdk" "${TMP_ROOT}/jdk.tar.gz"
  download "${JDK_URL}" "${TMP_ROOT}/jdk.tar.gz"
  mkdir -p "${TMP_ROOT}/jdk"
  tar -xzf "${TMP_ROOT}/jdk.tar.gz" -C "${TMP_ROOT}/jdk" --strip-components=1
  rm -f "${TMP_ROOT}/jdk.tar.gz"
fi
[ -x "${JDK}/bin/javac" ] || die "JDK 不可用: ${JDK}/bin/javac"
log "JDK: $("${JDK}/bin/javac" -version 2>&1)"

# ---------------------------------------------------------------------------
# 2. Maven
# ---------------------------------------------------------------------------
if [ ! -x "${MVN}" ]; then
  [ "${OFD_NO_DOWNLOAD:-0}" = "1" ] && die "缺少 Maven: ${MVN}（OFD_NO_DOWNLOAD=1 禁止下载）"
  log "未找到 Maven，开始下载 3.9.16 ..."
  rm -rf "${TMP_ROOT}/maven" "${TMP_ROOT}/maven.tar.gz"
  if ! download "${MVN_URL}" "${TMP_ROOT}/maven.tar.gz"; then
    log "主镜像失败，改用 archive.apache.org"
    download "${MVN_URL_FALLBACK}" "${TMP_ROOT}/maven.tar.gz"
  fi
  mkdir -p "${TMP_ROOT}/maven"
  tar -xzf "${TMP_ROOT}/maven.tar.gz" -C "${TMP_ROOT}/maven" --strip-components=1
  rm -f "${TMP_ROOT}/maven.tar.gz"
fi
[ -x "${MVN}" ] || die "Maven 不可用: ${MVN}"

# ---------------------------------------------------------------------------
# 3. 编译 + 复制依赖
# ---------------------------------------------------------------------------
rm -rf "${MODULE_DIR}/lib/classes"
mkdir -p "${MODULE_DIR}/lib/classes" "${MODULE_DIR}/lib/jars"

log "开始编译（Maven Central 首次下载依赖，之后走 ${M2} 缓存）..."
JAVA_HOME="${JDK}" "${MVN}" -B -q \
  -f "${MODULE_DIR}/pom.xml" \
  -Dmaven.repo.local="${M2}" \
  clean package

# ---------------------------------------------------------------------------
# 4. 校验产物
# ---------------------------------------------------------------------------
CLASS_COUNT="$(find "${MODULE_DIR}/lib/classes" -name '*.class' | wc -l | tr -d ' ')"
JAR_COUNT="$(find "${MODULE_DIR}/lib/jars" -maxdepth 1 -name '*.jar' | wc -l | tr -d ' ')"
[ "${CLASS_COUNT}" -gt 0 ] || die "编译产物为空: ${MODULE_DIR}/lib/classes"
[ "${JAR_COUNT}" -gt 0 ] || die "依赖 jar 为空: ${MODULE_DIR}/lib/jars"

rm -rf "${MODULE_DIR}/target"

log "完成: ${CLASS_COUNT} 个 class, ${JAR_COUNT} 个 jar, 依赖体积 $(du -sh "${MODULE_DIR}/lib/jars" | cut -f1)"
log "运行: bash ${MODULE_DIR}/test.sh"
