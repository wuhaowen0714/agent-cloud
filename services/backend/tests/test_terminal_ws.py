import uuid

from agent_cloud.v1 import sandbox_pb2
from agent_cloud_backend.api.terminal import (
    _MAX_TERMINALS_PER_USER,
    _active_terminals,
    _pump_worker_to_ws,
    _pump_ws_to_worker,
    _register,
    _release,
    _token_from_subprotocols,
)


class _FakeCall:
    """假 worker Terminal 流:记录 write,按脚本 yield server 消息。"""

    def __init__(self, outputs=()):
        self.written = []
        self._outputs = list(outputs)
        self.done = False

    async def write(self, msg):
        self.written.append(msg)

    async def done_writing(self):
        self.done = True

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for o in self._outputs:
            yield o


class _FakeWS:
    def __init__(self, incoming=()):
        self._incoming = list(incoming)
        self.sent = []
        self.closed = None

    async def receive(self):
        if self._incoming:
            return self._incoming.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_bytes(self, b):
        self.sent.append(b)

    async def close(self, code=1000):
        self.closed = code


def test_token_from_subprotocols():
    assert _token_from_subprotocols("bearer, abc.def.ghi") == "abc.def.ghi"
    assert _token_from_subprotocols("bearer,abc") == "abc"
    assert _token_from_subprotocols("") is None
    assert _token_from_subprotocols("abc") is None  # 缺 bearer 前缀
    assert _token_from_subprotocols("basic, abc") is None


async def test_pump_worker_to_ws_forwards_output():
    call = _FakeCall(outputs=[sandbox_pb2.TerminalServerMsg(output=b"hello-out")])
    ws = _FakeWS()
    await _pump_worker_to_ws(call, ws)
    assert ws.sent == [b"hello-out"]


async def test_pump_worker_to_ws_closes_on_exit():
    call = _FakeCall(outputs=[sandbox_pb2.TerminalServerMsg(exit_code=0)])
    ws = _FakeWS()
    await _pump_worker_to_ws(call, ws)
    assert ws.closed == 1000  # 收到 exit → 正常关闭


async def test_pump_ws_to_worker_forwards_input_and_resize():
    ws = _FakeWS(
        incoming=[
            {"type": "websocket.receive", "bytes": b"ls\n"},
            {"type": "websocket.receive", "text": '{"rows": 40, "cols": 100}'},
            {"type": "websocket.disconnect"},
        ]
    )
    call = _FakeCall()
    await _pump_ws_to_worker(ws, call)
    kinds = [m.WhichOneof("msg") for m in call.written]
    assert kinds == ["input", "resize"]
    assert call.written[0].input == b"ls\n"
    assert call.written[1].resize.rows == 40 and call.written[1].resize.cols == 100


async def test_pump_calls_on_activity_for_input_and_resize():
    # 续租 hook:每个 input/resize 帧触发 on_activity(端点据此 touch 续租)
    hits = {"n": 0}

    async def act():
        hits["n"] += 1

    ws = _FakeWS(
        incoming=[
            {"type": "websocket.receive", "bytes": b"x"},
            {"type": "websocket.receive", "text": '{"rows": 30, "cols": 90}'},
            {"type": "websocket.disconnect"},
        ]
    )
    await _pump_ws_to_worker(ws, _FakeCall(), on_activity=act)
    assert hits["n"] == 2


def test_register_caps_at_max_and_release_frees_slot():
    # 多终端:每用户至多 _MAX_TERMINALS_PER_USER 个;超限拒绝(不动已有);release 腾名额
    _active_terminals.clear()
    uid = uuid.uuid4()
    conns = [_FakeWS() for _ in range(_MAX_TERMINALS_PER_USER)]
    for ws in conns:
        assert _register(uid, ws) is True  # 满额前都能登记
    assert len(_active_terminals[uid]) == _MAX_TERMINALS_PER_USER
    overflow = _FakeWS()
    assert _register(uid, overflow) is False  # 超限被拒
    assert overflow not in _active_terminals[uid]  # 不入表,已有的不受影响
    _release(uid, conns[0])  # 摘掉一个 → 腾出名额
    assert conns[0] not in _active_terminals[uid]
    assert _register(uid, overflow) is True  # 现在能登记了
    for ws in list(_active_terminals[uid]):
        _release(uid, ws)
    assert uid not in _active_terminals  # 全摘除 → 删键


def test_release_is_safe_for_unregistered_ws():
    # release 一个从未登记的 ws 不报错(防御性)
    _active_terminals.clear()
    uid = uuid.uuid4()
    _release(uid, _FakeWS())  # 无键,静默
    _register(uid, _FakeWS())
    _release(uid, _FakeWS())  # 有键但非成员,静默(不误删别人)
    assert len(_active_terminals[uid]) == 1
