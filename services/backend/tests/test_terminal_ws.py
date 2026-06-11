from agent_cloud.v1 import sandbox_pb2
from agent_cloud_backend.api.terminal import (
    _pump_worker_to_ws,
    _pump_ws_to_worker,
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
