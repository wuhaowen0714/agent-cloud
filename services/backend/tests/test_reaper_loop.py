import asyncio

import pytest

from agent_cloud_backend.main import _reaper_loop


class _FakeManager:
    def __init__(self):
        self.calls = 0
        self.fired = asyncio.Event()

    async def reap_idle(self) -> int:
        self.calls += 1
        self.fired.set()
        return 0


async def test_reaper_loop_calls_reap_idle_periodically():
    mgr = _FakeManager()
    task = asyncio.create_task(_reaper_loop(0.01, mgr))
    await asyncio.wait_for(mgr.fired.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mgr.calls >= 1


async def test_reaper_loop_survives_reap_error():
    class _Boom(_FakeManager):
        async def reap_idle(self) -> int:
            self.calls += 1
            self.fired.set()
            raise RuntimeError("boom")

    mgr = _Boom()
    task = asyncio.create_task(_reaper_loop(0.01, mgr))
    await asyncio.wait_for(mgr.fired.wait(), timeout=2)
    await asyncio.sleep(0.05)  # 一次抛错后应继续循环
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mgr.calls >= 2
