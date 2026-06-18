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


async def _warm_one(client: AsyncOpenAI, model: str) -> bool:
    """焐单个模型并记录耗时,返回是否成功。失败只记日志、绝不外抛——免得拖垮同批其它模型或主循环。"""
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
        return True
    except asyncio.CancelledError:
        raise  # 关停时正常取消,向上传播
    except Exception as exc:  # noqa: BLE001 — 心跳失败不该影响 worker,记录即可
        logger.warning("keepwarm ping failed: %s %s", model, exc)
        return False


async def _warm_all(client: AsyncOpenAI, models: list[str]) -> int:
    """并发焐全部模型,返回失败的模型数。冷启按模型,多个模型可能同时凉,并发焐才能各自尽快恢复
    (而非串行排队)。返回失败数让主循环决定:有失败=撞冷/慢窗口→短间隔尽快重试。"""
    results = await asyncio.gather(*(_warm_one(client, m) for m in models))
    return sum(1 for ok in results if not ok)


async def keepwarm_loop(settings: WorkerSettings) -> None:
    """定时焐热平台 LLM 路由,消除 idle 后首回合的冷启延迟(sophnet 实测间歇性 ~60s 不吐字)。

    每 keepwarm_interval_seconds 给 keepwarm_models 里**每个**模型各发一次 _ping。⚠️ 冷启是按模型
    的(2026-06-18 线上实测:只焐 Flash 时 Pro 仍会冷),所以焐全部平台模型、缺一不可。仅平台 key;
    BYOK 会话各自端点不在此列。单模型 ping 失败(超时/网络)只记日志,绝不影响 worker。

    失败快速重试:某轮有模型 ping 失败(撞 sophnet 上游慢窗口,该模型路由这会儿凉/卡),下一轮改用
    keepwarm_retry_interval_seconds 这个**短**间隔尽快重焐,而非干等满 interval——最好情形把路由"凉
    着"的暴露窗口从 ~(timeout+interval) 压到 ~(timeout+retry)(实际取决于 sophnet 何时恢复)。全成功
    才回到正常 interval。注意:这只缩短 sophnet **恢复后**重新焐热的延迟;持续慢窗口里重试照样超时,
    治标不治本(根因在 sophnet 上游)。持续快速失败时无退避封顶(每 retry 一轮),但 ping 极小、可接受。
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
    retry_interval = settings.keepwarm_retry_interval_seconds
    models = settings.keepwarm_models
    logger.info(
        "keepwarm started: every %ss (retry %ss after a failed round), models=%s",
        interval,
        retry_interval,
        models,
    )
    while True:
        # 焐在前、sleep 在后:worker 一启动就先焐一轮,别干等一个 interval。
        failed = await _warm_all(client, models)
        # 有失败 → 短间隔尽快重试(sophnet 慢窗口刚过就抢着把路由焐回热);全成功 → 正常间隔。
        await asyncio.sleep(retry_interval if failed else interval)
