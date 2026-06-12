from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx
from agent_cloud_common import ToolCall, ToolResult, ToolSpec

from agent_cloud_worker.tools import ToolExecutor

# sophnet moltbot 搜索端点。config 默认 + server 直接构造的默认都引用它,避免多处硬编码漂移。
DEFAULT_SEARCH_ENDPOINT = "https://www.sophnet.com/api/open-apis/moltbot/search/web"

# web_search 工具(worker 原生:调外部搜索 API,**绝不进沙箱**——搜索 key 不下放最小信任的
# 沙箱)。端点是 sophnet moltbot,用一个**独立于 LLM 的专用 key**:用户可能 BYOK 成别家
# 模型(其 key 对 sophnet 端点无效),且不应拿用户账号为搜索买单,故搜索走平台专用 key。
# 返回排序结果(标题+链接+摘要)回填给模型综合;模型可再用 bash(curl)打开某条 url 读全文。
WEB_SEARCH_SPEC = ToolSpec(
    name="web_search",
    description=(
        "Search the web and get back a ranked list of results (title, URL, snippet). Use this "
        "whenever the answer depends on facts you may not know or that change over time — news, "
        "events, scores, prices, releases, documentation, people, products. Prefer this over "
        "guessing, and over fetching a search engine yourself with the bash tool. After "
        "searching you may open a result's URL with the bash tool (curl) to read the full page."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, e.g. '2026 世界杯 6月12日 比分'.",
            }
        },
        "required": ["query"],
    },
)


def web_search_enabled(enabled_tools: list[str]) -> bool:
    """空 enabled_tools = 全部(含 web_search),与其它工具一致;否则需显式列出。"""
    return not enabled_tools or "web_search" in enabled_tools


# query -> 给模型的 markdown 结果文本;失败抛异常,由 executor 收敛成 is_error 结果。
SearchFn = Callable[[str], Awaitable[str]]

_MAX_SNIPPET_CHARS = 600  # 单条摘要防御性上限(sophnet 摘要约 200 字,偶发超长不至于撑爆上下文)


def _format_results(results: list, max_results: int) -> str:
    """把 sophnet result[] 格式化成给模型的紧凑 markdown:每条「序号. 标题 / url / 摘要」。"""
    items = [r for r in results if isinstance(r, dict)][: max(1, max_results)]
    if not items:
        return "No results found."
    blocks = []
    for i, r in enumerate(items, 1):
        title = (r.get("title") or "").strip() or "(untitled)"
        url = (r.get("url") or "").strip()
        snippet = " ".join((r.get("content") or "").split())  # 压扁换行/多空格
        if len(snippet) > _MAX_SNIPPET_CHARS:
            snippet = snippet[:_MAX_SNIPPET_CHARS] + "…"
        block = f"{i}. {title}\n{url}" if url else f"{i}. {title}"
        if snippet:
            block += f"\n{snippet}"
        blocks.append(block)
    return "\n\n".join(blocks)


def make_sophnet_searcher(
    *,
    endpoint: str,
    api_key: str,
    max_results: int,
    timeout: float = 15.0,
    transport: httpx.BaseTransport | None = None,
) -> SearchFn:
    """造一个调 sophnet moltbot 搜索端点的 SearchFn。Bearer = 平台搜索专用 key。

    transport 仅供测试注入(httpx.MockTransport),生产传 None 用默认网络栈。
    """

    async def search(query: str) -> str:
        async with httpx.AsyncClient(
            timeout=timeout, transport=transport, follow_redirects=True
        ) as client:
            resp = await client.post(
                endpoint,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": f"Bearer {api_key}",
                },
                content=json.dumps({"query": query}, ensure_ascii=False).encode("utf-8"),
            )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("search backend returned an unexpected payload")
        # 业务错误信封:HTTP 200 但 status!=0 / error 非空(配额、限流、key 失效等,网关仍回
        # 200)。必须当失败抛出——否则 result=null 会被当成"查无结果",让模型把后端故障误当成
        # 权威的"全网无此事"。message/error 是服务端文案、不含 key,可安全外带给模型。
        if data.get("status") not in (0, None) or data.get("error"):
            detail = data.get("message") or data.get("error") or "unknown error"
            raise RuntimeError(f"search backend error: {detail}")
        results = data.get("result")
        return _format_results(results if isinstance(results, list) else [], max_results)

    return search


class WebSearchExecutor:
    """装饰 ToolExecutor:加 worker 原生的 ``web_search`` 工具。

    ``web_search`` 调外部搜索 API(平台专用 key),在 worker 处理、**绝不转发沙箱**;其余工具
    委托内层 executor。搜索失败(HTTP/超时/解析)收敛成 is_error 结果,不让异常冲掉整个回合。
    """

    def __init__(self, inner: ToolExecutor, *, enabled: bool, search_fn: SearchFn) -> None:
        self._inner = inner
        self._enabled = enabled
        self._search_fn = search_fn

    def specs(self) -> list[ToolSpec]:
        specs = list(self._inner.specs())
        if self._enabled:
            specs.append(WEB_SEARCH_SPEC)
        return specs

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != "web_search":
            return await self._inner.execute(call)
        # 在 worker(可信侧)强制启用判定:不只是从 prompt 隐藏(与 remember/sandbox 一致,
        # 防 skill 等不可信内容诱导调用被禁工具)。
        if not self._enabled:
            return ToolResult(
                call_id=call.id, content="tool not enabled: web_search", is_error=True
            )
        args = call.arguments or {}
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(
                call_id=call.id,
                content="web_search: 'query' (non-empty string) is required",
                is_error=True,
            )
        try:
            content = await self._search_fn(query.strip())
            return ToolResult(call_id=call.id, content=content, is_error=False)
        except Exception as exc:  # noqa: BLE001 — HTTP/超时/解析失败转 is_error,让模型换路
            # 带类型名:httpx.ReadTimeout 等的 str(exc) 常为空串,只剩 "web_search failed:"。
            return ToolResult(
                call_id=call.id,
                content=f"web_search failed: {type(exc).__name__}: {exc}",
                is_error=True,
            )
