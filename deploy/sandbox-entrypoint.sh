#!/usr/bin/env sh
# /workspace 是挂进来的用户卷,新用户初始为空。先建好依赖路由目录(HOME / pip --user /
# npm 前缀),再启动沙箱服务。这些目录在卷里 → 装的依赖跨容器重建保留(spec §8.1)。
set -e
mkdir -p /workspace/.home/.local/bin /workspace/.home/.cache /workspace/.npm-global/bin
exec python -m agent_cloud_sandbox
