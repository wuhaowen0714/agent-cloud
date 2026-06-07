from __future__ import annotations

import asyncio

import grpc


async def grpc_endpoint_alive(endpoint: str, timeout: float = 2.0) -> bool:
    """gRPC 连通性探活:能在 timeout 内建立 HTTP/2 通道即视为存活。

    探测的是连通性(进程没了 → 连接被拒/超时 → False),不是完整健康检查;
    足以发现「沙箱进程已死」这一常见情形(spec §10 的重建路径)。供生产 provisioner
    作为 SandboxManager 的 health_check 注入;进程内开发恒为存活,无需注入。
    """
    try:
        async with grpc.aio.insecure_channel(endpoint) as channel:
            await asyncio.wait_for(channel.channel_ready(), timeout)
        return True
    except Exception:
        return False
