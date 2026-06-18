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


async def _warm_one(client: AsyncOpenAI, model: str) -> None:
    """焐单个模型并记录耗时。失败只记日志、绝不外抛——免得拖垮同批其它模型或主循环。"""
    try:
        t0 = time.monotonic()
        await _ping(client, model)
        elapsed = time.monotonic() - t0
        # 慢 ping = 这个模型撞了冷路由(上游冷启 ~60s);连续慢 = interval 太松、它在两次心跳之间
        # 凉了,该调小 interval。快 ping = 这个模型一直热着,正常。
        if elapsed > 10.0:
            logger.warning(
                "keepwarm ping slow: %s %.1fs (route had gone cold — shorten "
                "keepwarm_interval_seconds)",
                model,
                elapsed,
            )
        else:
            logger.info("keepwarm ping ok: %s %.1fs", model, elapsed)
    except asyncio.CancelledError:
        raise  # 关停时正常取消,向上传播
    except Exception as exc:  # noqa: BLE001 — 心跳失败不该影响 worker,记录即可
        logger.warning("keepwarm ping failed: %s %s", model, exc)


async def _warm_all(client: AsyncOpenAI, models: list[str]) -> None:
    """并发焐全部模型:冷启按模型,多个模型可能同时凉,并发焐才能各自尽快恢复(而非串行排队)。"""
    await asyncio.gather(*(_warm_one(client, m) for m in models))


async def keepwarm_loop(settings: WorkerSettings) -> None:
    """定时焐热平台 LLM 路由,消除 idle 后首回合的冷启延迟(sophnet 实测间歇性 ~60s 不吐字)。

    每 keepwarm_interval_seconds 给 keepwarm_models 里**每个**模型各发一次 _ping。⚠️ 冷启是按模型
    的(2026-06-18 线上实测:只焐 Flash 时 Pro 仍会冷),所以焐全部平台模型、缺一不可。仅平台 key;
    BYOK 会话各自端点不在此列。单模型 ping 失败(超时/网络)只记日志,等下一轮——绝不影响 worker。
    """
    if not settings.keepwarm_enabled:
        logger.info("keepwarm disabled")
        return
    if not settings.openai_api_key or not settings.keepwarm_models:
        logger.info("keepwarm skipped: no platform api_key or keepwarm_models configured")
        return

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.keepwarm_timeout_seconds,
        max_retries=0,  # 心跳失败就等下一轮,别自重试拖长这次循环
    )
    interval = settings.keepwarm_interval_seconds
    models = settings.keepwarm_models
    logger.info("keepwarm started: every %ss, models=%s", interval, models)
    while True:
        # 焐在前、sleep 在后:worker 一启动就先焐一轮,别干等一个 interval。
        await _warm_all(client, models)
        await asyncio.sleep(interval)
