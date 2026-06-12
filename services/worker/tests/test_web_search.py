import json

import httpx
import pytest
from agent_cloud_common import ToolCall, ToolResult, ToolSpec
from agent_cloud_worker.web_search import (
    WebSearchExecutor,
    _format_results,
    make_sophnet_searcher,
    web_search_enabled,
)


class _FakeInner:
    """内层 executor 替身:有自己的 specs,execute 记录被转发的调用。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def specs(self) -> list[ToolSpec]:
        return [ToolSpec(name="bash", description="", input_schema={})]

    async def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call_id=call.id, content="inner-handled", is_error=False)


async def _fake_search(query: str) -> str:
    return f"results for: {query}"


def test_web_search_enabled_helper():
    assert web_search_enabled([]) is True  # 空 = 全含(与 bash/remember 一致)
    assert web_search_enabled(["web_search"]) is True
    assert web_search_enabled(["bash"]) is False


def test_spec_appended_when_enabled():
    ex = WebSearchExecutor(_FakeInner(), enabled=True, search_fn=_fake_search)
    names = [s.name for s in ex.specs()]
    assert "bash" in names and "web_search" in names


def test_spec_hidden_when_disabled():
    ex = WebSearchExecutor(_FakeInner(), enabled=False, search_fn=_fake_search)
    names = [s.name for s in ex.specs()]
    assert "web_search" not in names and "bash" in names


async def test_executes_web_search_via_search_fn():
    ex = WebSearchExecutor(_FakeInner(), enabled=True, search_fn=_fake_search)
    res = await ex.execute(ToolCall(id="c1", name="web_search", arguments={"query": "世界杯"}))
    assert res.is_error is False
    assert "results for: 世界杯" in res.content


async def test_delegates_non_web_search_to_inner():
    inner = _FakeInner()
    ex = WebSearchExecutor(inner, enabled=True, search_fn=_fake_search)
    res = await ex.execute(ToolCall(id="c2", name="bash", arguments={"command": "ls"}))
    assert res.content == "inner-handled"
    assert len(inner.calls) == 1  # 非 web_search 转发给内层


async def test_empty_query_is_error():
    ex = WebSearchExecutor(_FakeInner(), enabled=True, search_fn=_fake_search)
    res = await ex.execute(ToolCall(id="c3", name="web_search", arguments={"query": "  "}))
    assert res.is_error is True
    assert "query" in res.content


async def test_search_failure_becomes_is_error():
    async def boom(query: str) -> str:
        raise httpx.ConnectTimeout("timeout")

    ex = WebSearchExecutor(_FakeInner(), enabled=True, search_fn=boom)
    res = await ex.execute(ToolCall(id="c4", name="web_search", arguments={"query": "x"}))
    assert res.is_error is True
    assert "web_search failed" in res.content


async def test_disabled_web_search_call_is_error():
    # enabled=False 时即使模型硬调 web_search 也拒绝(可信侧强制,非仅隐藏)
    ex = WebSearchExecutor(_FakeInner(), enabled=False, search_fn=_fake_search)
    res = await ex.execute(ToolCall(id="c5", name="web_search", arguments={"query": "x"}))
    assert res.is_error is True


def test_format_results_caps_and_formats():
    results = [{"title": f"T{i}", "url": f"http://u/{i}", "content": f"C{i}"} for i in range(20)]
    out = _format_results(results, max_results=8)
    assert out.count("http://u/") == 8  # 截到 max_results
    assert "1. T0" in out and "C0" in out


def test_format_results_empty():
    assert _format_results([], max_results=8) == "No results found."


def test_format_results_truncates_long_snippet():
    out = _format_results([{"title": "T", "url": "U", "content": "字" * 1000}], max_results=8)
    assert "…" in out and len(out) < 1000


async def test_sophnet_searcher_builds_request_and_parses():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["ct"] = request.headers.get("content-type")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "status": 0,
                "result": [
                    {"title": "南非0-2墨西哥", "url": "http://163.com/x", "content": "揭幕战"}
                ],
            },
        )

    searcher = make_sophnet_searcher(
        endpoint="https://sophnet.test/moltbot/search/web",
        api_key="sk-search-key",
        max_results=8,
        transport=httpx.MockTransport(handler),
    )
    out = await searcher("世界杯 6月12")
    assert captured["method"] == "POST"
    assert captured["url"] == "https://sophnet.test/moltbot/search/web"
    assert captured["auth"] == "Bearer sk-search-key"  # 专用搜索 key,非 LLM key
    assert captured["ct"] == "application/json; charset=utf-8"  # 真实 API 要求该 header
    assert captured["body"] == {"query": "世界杯 6月12"}
    assert "南非0-2墨西哥" in out and "http://163.com/x" in out


async def test_sophnet_searcher_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    searcher = make_sophnet_searcher(
        endpoint="https://sophnet.test/x",
        api_key="bad",
        max_results=8,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await searcher("q")


async def test_sophnet_searcher_raises_on_business_error_envelope():
    # 真实网关:业务失败也走 HTTP 200,带 status!=0 / error。必须抛错,不能吞成"无结果"
    # (否则模型把后端故障误当权威的"全网无此事")。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": 1, "message": "请求过于频繁", "result": None, "error": None}
        )

    searcher = make_sophnet_searcher(
        endpoint="https://sophnet.test/x",
        api_key="k",
        max_results=8,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="请求过于频繁"):
        await searcher("q")


async def test_sophnet_searcher_tolerates_non_list_result():
    # result 字段结构异常(非 list)→ 不崩,当作无结果。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 0, "result": "oops"})

    searcher = make_sophnet_searcher(
        endpoint="https://sophnet.test/x",
        api_key="k",
        max_results=8,
        transport=httpx.MockTransport(handler),
    )
    assert await searcher("q") == "No results found."
