import asyncio

import agent_cloud_backend.main as main_mod


async def test_lifespan_starts_and_cancels_scheduler(monkeypatch):
    started = asyncio.Event()

    async def fake_sched(settings):
        started.set()
        await asyncio.sleep(3600)

    async def fake_reaper(*a, **k):
        await asyncio.sleep(3600)

    monkeypatch.setattr(main_mod, "scheduler_loop", fake_sched)
    monkeypatch.setattr(main_mod, "_reaper_loop", fake_reaper)
    app = main_mod.create_app()
    async with main_mod.lifespan(app):
        await asyncio.wait_for(started.wait(), timeout=2)
    # 退出后任务已被取消(没有挂起任务泄漏)—— 不抛即视为收尾正常


async def test_lifespan_skips_scheduler_when_disabled(monkeypatch):
    called = {"n": 0}

    async def fake_sched(settings):
        called["n"] += 1

    async def fake_reaper(*a, **k):
        await asyncio.sleep(3600)

    monkeypatch.setattr(main_mod, "scheduler_loop", fake_sched)
    monkeypatch.setattr(main_mod, "_reaper_loop", fake_reaper)
    monkeypatch.setenv("AGENT_CLOUD_SCHEDULER_ENABLED", "false")
    app = main_mod.create_app()
    async with main_mod.lifespan(app):
        await asyncio.sleep(0.05)
    assert called["n"] == 0
