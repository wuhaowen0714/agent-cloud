#!/usr/bin/env bash
# 移动端发版:构建 release APK + 生成 release.json + 上传到 st-e nginx 托管目录。
#
# 用法:
#   ./scripts/release.sh <version> <build> [notes] [--force]
# 例:
#   ./scripts/release.sh 1.0.1 2 "修复登录问题"
#   ./scripts/release.sh 1.1.0 3 "重大更新,建议立即升级" --force
#
# 前置(一次性,见 OTA.md):st-e 上 nginx 托管 /app/download/ + 后端挂载 /data/app-releases。
set -euo pipefail

VERSION="${1:?用法: release.sh <version> <build> [notes] [--force]}"
BUILD="${2:?需要 build 号(单调递增整数,App 用它比对)}"
NOTES="${3:-}"
FORCE="false"
[[ "${4:-}" == "--force" ]] && FORCE="true"

SSH="${ST_SSH:-st}"                        # SSH host alias(~/.ssh/config,含 9022 端口)
REMOTE_DIR="${ST_RELEASE_DIR:-/data/app-releases}"  # nginx 托管 + 后端挂载目录
BASE_URL="${APP_BASE_URL:-https://app.sophclaw.icu:18080}"
APK="agent-cloud-${BUILD}.apk"

cd "$(dirname "$0")/.."

echo "▶ 构建 APK: v${VERSION} (build ${BUILD}) force=${FORCE}"
flutter build apk --release \
  --build-name="${VERSION}" --build-number="${BUILD}" \
  --dart-define=API_BASE="${BASE_URL}/api"

LOCAL_APK="build/app/outputs/flutter-apk/app-release.apk"
[[ -f "$LOCAL_APK" ]] || { echo "✗ 未找到 $LOCAL_APK"; exit 1; }

# release.json:App GET /app/version 后端读它返回。先传 APK 再切 json,避免指向尚未上传的包。
RELEASE_JSON="$(mktemp)"
cat > "$RELEASE_JSON" <<EOF
{
  "version": "${VERSION}",
  "build": ${BUILD},
  "url": "${BASE_URL}/app/download/${APK}",
  "force": ${FORCE},
  "notes": "${NOTES}"
}
EOF

echo "▶ 上传到 ${SSH}:${REMOTE_DIR}"
ssh "${SSH}" "mkdir -p ${REMOTE_DIR}"
scp "${LOCAL_APK}" "${SSH}:${REMOTE_DIR}/${APK}"
scp "$RELEASE_JSON" "${SSH}:${REMOTE_DIR}/release.json"
rm -f "$RELEASE_JSON"

echo "✓ 发版完成 v${VERSION} (build ${BUILD}) force=${FORCE}"
echo "  下载: ${BASE_URL}/app/download/${APK}"
echo "  App 下次启动或'设置→检查更新'即提示。"
