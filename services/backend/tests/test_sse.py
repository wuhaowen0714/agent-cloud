import grpc
from agent_cloud_backend.turn.sse import error_sse, format_sse, turn_event_to_sse
from agent_cloud_common import (
    TextDelta,
    ThinkingDelta,
    ToolCallProgress,
    ToolCallStarted,
    ToolResultEvent,
)


def test_text_delta_mapping():
    assert turn_event_to_sse(TextDelta(text="hi")) == {"type": "text_delta", "text": "hi"}


def test_thinking_delta_mapping():
    assert turn_event_to_sse(ThinkingDelta(text="hmm")) == {"type": "thinking_delta", "text": "hmm"}


def test_tool_call_start_mapping():
    out = turn_event_to_sse(ToolCallStarted(call_id="c1", name="bash", arguments={"command": "x"}))
    assert out == {
        "type": "tool_call_start",
        "call_id": "c1",
        "tool": "bash",
        "args": {"command": "x"},
    }


def test_tool_result_mapping():
    out = turn_event_to_sse(ToolResultEvent(call_id="c1", content="out", is_error=True))
    assert out == {
        "type": "tool_result",
        "call_id": "c1",
        "result": "out",
        "is_error": True,
    }


def test_format_sse():
    assert (
        format_sse({"type": "text_delta", "text": "hi"})
        == 'data: {"type": "text_delta", "text": "hi"}\n\n'
    )


def test_error_sse_recoverable_codes():
    e = error_sse(grpc.StatusCode.UNAVAILABLE)
    assert e["type"] == "error" and e["recoverable"] is True
    assert "UNAVAILABLE" not in e["message"]  # generic, no internal detail
    e2 = error_sse(grpc.StatusCode.INVALID_ARGUMENT)
    assert e2["recoverable"] is False


def test_tool_call_progress_mapping():
    out = turn_event_to_sse(
        ToolCallProgress(
            call_id="c1", name="write_file", args_chars=1234, lines=5, path_hint="a.py"
        )
    )
    assert out == {
        "type": "tool_call_progress",
        "call_id": "c1",
        "tool": "write_file",
        "args_chars": 1234,
        "lines": 5,
        "path": "a.py",
    }
