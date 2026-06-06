from __future__ import annotations

# 跨服务共享的 gRPC 单条消息上限。gRPC 默认接收上限是 4MB,一个长回合的
# RunTurnResponse(打包了本回合所有 new_messages)很容易超过 → RESOURCE_EXHAUSTED。
# 这里设一个明确、足够大的上限,worker 服务端 / sandbox channel / 2d 后端的 Worker
# client channel 必须统一用它(尤其是接收侧 max_receive_message_length),否则一端
# 放行、另一端仍按默认 4MB 截断。
MAX_GRPC_MESSAGE_BYTES = 32 * 1024 * 1024
