import asyncio
import uuid

from agent_cloud_backend.turn.hub import ActiveTurn, TurnHub, subscribe


def _sid():
    return uuid.uuid4()


async def _collect(active, out):
    async for chunk in subscribe(active):
        out.append(chunk)


async def test_hub_register_get_remove():
    hub = TurnHub()
    sid = _sid()
    assert hub.get(sid) is None
    active = ActiveTurn(session_id=sid)
    hub.register(active)
    assert hub.get(sid) is active
    hub.remove(sid)
    assert hub.get(sid) is None


async def test_subscribe_replays_buffer_then_live_then_ends_on_done():
    active = ActiveTurn(session_id=_sid())
    await active.emit({"type": "text_delta", "text": "a"})  # buffered before subscribe
    out: list[str] = []
    task = asyncio.create_task(_collect(active, out))
    await asyncio.sleep(0)  # let it replay
    await active.emit({"type": "text_delta", "text": "b"})  # live
    await active.finish()
    await task
    joined = "".join(out).replace(" ", "")
    assert '"text":"a"' in joined
    assert '"text":"b"' in joined


async def test_subscribe_two_subscribers_each_get_all():
    active = ActiveTurn(session_id=_sid())
    a: list[str] = []
    b: list[str] = []
    t1 = asyncio.create_task(_collect(active, a))
    t2 = asyncio.create_task(_collect(active, b))
    await asyncio.sleep(0)
    await active.emit({"type": "x"})
    await active.finish()
    await asyncio.gather(t1, t2)
    assert len(a) == 1 and len(b) == 1


async def test_subscribe_returns_immediately_when_already_done():
    active = ActiveTurn(session_id=_sid())
    await active.emit({"type": "turn_done"})
    await active.finish()
    out: list[str] = []
    await _collect(active, out)  # should not hang
    assert len(out) == 1
