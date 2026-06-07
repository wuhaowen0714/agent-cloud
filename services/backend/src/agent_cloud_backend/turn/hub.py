from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from agent_cloud_backend.turn.sse import format_sse


@dataclass
class ActiveTurn:
    session_id: uuid.UUID
    events: list[dict] = field(default_factory=list)
    done: bool = False
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None

    async def emit(self, event: dict) -> None:
        async with self.cond:
            self.events.append(event)
            self.cond.notify_all()

    async def finish(self) -> None:
        async with self.cond:
            self.done = True
            self.cond.notify_all()


class TurnHub:
    """进程内"正在跑的回合"注册表。一会话至多一个(由会话锁保证)。"""

    def __init__(self) -> None:
        self._turns: dict[uuid.UUID, ActiveTurn] = {}

    def get(self, session_id: uuid.UUID) -> ActiveTurn | None:
        return self._turns.get(session_id)

    def register(self, active: ActiveTurn) -> None:
        self._turns[active.session_id] = active

    def remove(self, session_id: uuid.UUID) -> None:
        self._turns.pop(session_id, None)

    def all_tasks(self) -> list[asyncio.Task]:
        return [a.task for a in self._turns.values() if a.task is not None]

    def session_ids(self) -> list[uuid.UUID]:
        return list(self._turns.keys())


_HUB = TurnHub()


def get_turn_hub() -> TurnHub:
    return _HUB


async def subscribe(active: ActiveTurn) -> AsyncIterator[str]:
    """补播已发事件 + 实时续看,直到 done 且全部吐完。多订阅者各自游标。"""
    idx = 0
    while True:
        async with active.cond:
            while idx >= len(active.events) and not active.done:
                await active.cond.wait()
            batch = active.events[idx:]
            idx = len(active.events)
            done = active.done
        for ev in batch:
            yield format_sse(ev)
        if done and idx >= len(active.events):
            return
