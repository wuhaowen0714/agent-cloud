#!/usr/bin/env bash
set -euo pipefail
# 从仓库根运行。把 protos/ 下所有 .proto 生成为 Python 桩,落进 packages/common/src。
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="packages/common/src"
uv run --package agent-cloud-common python -m grpc_tools.protoc \
  -I protos \
  --python_out="$OUT" \
  --grpc_python_out="$OUT" \
  protos/agent_cloud/v1/sandbox.proto \
  protos/agent_cloud/v1/worker.proto
touch "$OUT/agent_cloud/__init__.py" "$OUT/agent_cloud/v1/__init__.py"
echo "generated stubs under $OUT/agent_cloud/v1/"
