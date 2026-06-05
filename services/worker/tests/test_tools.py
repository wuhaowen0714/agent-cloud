from agent_cloud_common import ToolCall
from agent_cloud_worker.tools import LocalToolExecutor, builtin_tools


def _executor(tmp_path):
    return LocalToolExecutor(workdir=tmp_path, tools=builtin_tools())


def test_specs_lists_builtin_tools(tmp_path):
    names = {s.name for s in _executor(tmp_path).specs()}
    assert {"bash", "write_file", "read_file"} <= names


async def test_write_then_read(tmp_path):
    ex = _executor(tmp_path)
    w = await ex.execute(
        ToolCall(id="1", name="write_file", arguments={"path": "a.txt", "content": "hello"})
    )
    assert w.is_error is False
    r = await ex.execute(ToolCall(id="2", name="read_file", arguments={"path": "a.txt"}))
    assert r.is_error is False
    assert r.content == "hello"
    assert (tmp_path / "a.txt").read_text() == "hello"


async def test_bash_runs_in_workdir(tmp_path):
    ex = _executor(tmp_path)
    r = await ex.execute(ToolCall(id="1", name="bash", arguments={"command": "echo hi"}))
    assert r.is_error is False
    assert "hi" in r.content


async def test_bash_nonzero_exit_is_error(tmp_path):
    ex = _executor(tmp_path)
    r = await ex.execute(ToolCall(id="1", name="bash", arguments={"command": "exit 3"}))
    assert r.is_error is True


async def test_unknown_tool_returns_error(tmp_path):
    ex = _executor(tmp_path)
    r = await ex.execute(ToolCall(id="1", name="nope", arguments={}))
    assert r.is_error is True
    assert "unknown tool" in r.content.lower()
