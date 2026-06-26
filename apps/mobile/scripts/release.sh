#!/usr/bin/env bash
# 移动端发版:构建 release APK + 生成 release.json + 上传到 st-e。
#
# 用法:
#   ./scripts/release.sh <version> [notes] [--force]
# 例:
#   ./scripts/release.sh 1.0.1 "修复登录问题"
#   ./scripts/release.sh 1.1.0 "重大更新,建议升级" --force
#
# build 号自动取 main 提交数(单调递增、同 commit 幂等、绝不撞号);只允许在 main 分支发版
# —— 发版 = 给用户推 main 上的统一版本。多 worktree 并行开发时各自本地 flutter build apk
# 测试,不走发版,从而不会撞 build 号 / 覆盖 release.json。
# 前置(一次性,见 OTA.md):后端挂载 /opt/agent-cloud/data/app-releases + AGENT_CLOUD_APP_RELEASE_FILE。
set -euo pipefail

VERSION="${1:?用法: release.sh <version> [notes] [--force]}"
NOTES="${2:-}"
FORCE="false"
[[ "${3:-}" == "--force" ]] && FORCE="true"

SSH="${ST_SSH:-st}"                        # SSH host alias(~/.ssh/config,含 9022 端口)
REMOTE_DIR="${ST_RELEASE_DIR:-/opt/agent-cloud/data/app-releases}"  # backend 只读挂载目录
BASE_URL="${APP_BASE_URL:-https://app.sophclaw.icu:18080}"

cd "$(dirname "$0")/.."

# 发版收口 main:防多 worktree 并行发版打架(撞 build 号 / 互相覆盖 release.json)。
BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" != "main" ]]; then
  echo "✗ 发版必须在 main 分支(当前: ${BRANCH:-detached HEAD})。" >&2
  echo "  发版 = 给用户推 main 上的统一版本。到主 checkout: git checkout main && git pull" >&2
  echo "  开发分支想测自己的改动,本地 'flutter build apk' 装,别走发版。" >&2
  exit 1
fi
git pull --ff-only
# build 号自动 = main 提交数:单调递增、同 commit 幂等、绝不撞号
BUILD="$(git rev-list --count HEAD)"
APK="agent-cloud-${BUILD}.apk"
echo "ℹ build 号自动取 = ${BUILD}(main 提交数)"

echo "▶ 构建 APK: v${VERSION} (build ${BUILD}) force=${FORCE}"
flutter build apk --release --target-platform android-arm64 \
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
  "url": "${BASE_URL}/api/app/download/${APK}",
  "force": ${FORCE},
  "notes": "${NOTES}"
}
EOF

echo "▶ 上传到 ${SSH}:${REMOTE_DIR}"
ssh "${SSH}" "mkdir -p ${REMOTE_DIR}"
scp "${LOCAL_APK}" "${SSH}:${REMOTE_DIR}/${APK}"
scp "$RELEASE_JSON" "${SSH}:${REMOTE_DIR}/release.json"
rm -f "$RELEASE_JSON"

# 清理旧 APK:release.json 已切到新版,同目录其它 agent-cloud-*.apk 无用,删掉只留当前包
ssh "${SSH}" "find '${REMOTE_DIR}' -maxdepth 1 -name 'agent-cloud-*.apk' ! -name '${APK}' -delete" 2>/dev/null || true

echo "✓ 发版完成 v${VERSION} (build ${BUILD}) force=${FORCE}"
echo "  下载: ${BASE_URL}/api/app/download/${APK}"
echo "  App 下次启动或'设置→检查更新'即提示。"
