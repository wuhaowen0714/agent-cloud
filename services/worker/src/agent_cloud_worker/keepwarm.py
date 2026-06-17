from __future__ import annotations

import asyncio
import logging
import time

from openai import AsyncOpenAI

from agent_cloud_worker.config import WorkerSettings

logger = logging.getLogger(__name__)


async def _ping(client: AsyncOpenAI, model: str) -> None:
    """给平台端点发一个极小请求(max_tokens=1),触达上游路由把它焐热。"""
    await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
    )


async def keepwarm_loop(settings: WorkerSettings) -> None:
    """定时焐热平台 LLM 路由,消除 idle 后首回合的冷启延迟(sophnet 实测间歇性 ~60s 不吐字)。

    每 keepwarm_interval_seconds 发一次 _ping。焐任一模型即焐热整个账号路由(实测用一个模型后
    其它也快),所以只焐最便宜的 keepwarm_model。仅平台 key;BYOK 会话各自端点不在此列。
    单次 ping 失败(超时/网络)只记日志,等下一轮——绝不影响 worker 主流程。
    """
    if not settings.keepwarm_enabled:
        logger.info("keepwarm disabled")
        return
    if not settings.openai_api_key or not settings.keepwarm_model:
        logger.info("keepwarm skipped: no platform api_key or keepwarm_model configured")
        return

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.keepwarm_timeout_seconds,
        max_retries=0,  # 心跳失败就等下一轮,别自重试拖长这次循环
    )
    interval = settings.keepwarm_interval_seconds
    logger.info("keepwarm started: every %ss, model=%s", interval, settings.keepwarm_model)
    while True:
        # ping 在前、sleep 在后:worker 一启动就先焐一次,别干等一个 interval。
        try:
            t0 = time.monotonic()
            await _ping(client, settings.keepwarm_model)
            elapsed = time.monotonic() - t0
            # 慢 ping = 这次撞了冷路由(上游冷启 ~60s);连续慢 = interval 太松、路由在两次心跳
            # 之间凉了,该调小 interval。快 ping = 路由一直热着,正常。
            if elapsed > 10.0:
                logger.warning(
                    "keepwarm ping slow: %.1fs (route had gone cold — shorten "
                    "keepwarm_interval_seconds)",
                    elapsed,
                )
            else:
                logger.info("keepwarm ping ok: %.1fs", elapsed)
        except asyncio.CancelledError:
            raise  # 关停时正常取消,向上传播
        except Exception as exc:  # noqa: BLE001 — 心跳失败不该影响 worker,记录即可
            logger.warning("keepwarm ping failed: %s", exc)
        await asyncio.sleep(interval)
