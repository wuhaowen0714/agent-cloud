"""真实端点联调:用配置的 OpenAI 兼容端点跑 OpenAIProvider 的 complete / stream。

走的是生产同一条代码路径(build_provider_factory -> OpenAIProvider),不需要
Postgres / 沙箱 / 后端。

用法:
    cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/worker
    export AGENT_CLOUD_WORKER_OPENAI_API_KEY="你的key"
    export AGENT_CLOUD_WORKER_OPENAI_BASE_URL="https://你的端点/v1"
    uv run python scripts/smoke_openai.py <model>

可选:
    # OpenAI 推理模型(o 系列 / gpt-5 reasoning)要换 max-tokens 参数名:
    export AGENT_CLOUD_WORKER_MAX_TOKENS_PARAM=max_completion_tokens
    # 调小/调大单次输出上限(默认 4096):
    export AGENT_CLOUD_WORKER_REQUEST_MAX_TOKENS=1024
"""

from __future__ import annotations

import asyncio
import sys

from agent_cloud_common import CompletionRequest, Message, Role, ToolSpec
from agent_cloud_worker.config import get_worker_settings
from agent_cloud_worker.factory import build_provider_factory
from agent_cloud_worker.provider import (
    ProviderCompleted,
    ProviderTextDelta,
    ProviderThinkingDelta,
)

WEATHER = ToolSpec(
    name="get_weather",
    description="Get the current weather for a city.",
    input_schema={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
)


async def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else ""
    if not model:
        print("用法: uv run python scripts/smoke_openai.py <model>  (model 是你端点上的模型名)")
        sys.exit(2)

    settings = get_worker_settings()
    print(
        f"base_url={settings.openai_base_url}\n"
        f"model={model}  max_tokens_param={settings.max_tokens_param}  "
        f"max_tokens={settings.request_max_tokens}  "
        f"api_key={'set' if settings.openai_api_key else 'MISSING'}"
    )
    if not settings.openai_api_key:
        print("ERROR: 先 export AGENT_CLOUD_WORKER_OPENAI_API_KEY")
        sys.exit(1)

    provider = build_provider_factory(settings)(model, "openai", "smoke")

    # 1) 纯文本
    print("\n[1] complete (纯文本)")
    r = await provider.complete(
        CompletionRequest(
            system="You are concise.",
            messages=[Message(role=Role.USER, text="Say hello in exactly five words.")],
            tools=[],
        )
    )
    print("  text :", r.message.text)
    print("  usage:", r.usage)

    # 2) 工具调用(模型应返回一个 get_weather 的 tool_call)
    print("\n[2] complete (期望触发工具调用)")
    r = await provider.complete(
        CompletionRequest(
            system="Use the get_weather tool when the user asks about weather.",
            messages=[Message(role=Role.USER, text="What's the weather in Paris right now?")],
            tools=[WEATHER],
        )
    )
    print("  text       :", r.message.text)
    print("  tool_calls :", [(tc.name, tc.arguments) for tc in r.message.tool_calls])
    print("  usage      :", r.usage)

    # 3) 流式
    print("\n[3] stream (流式增量)")
    print("  ", end="")
    async for ev in provider.stream(
        CompletionRequest(
            system="You are concise.",
            messages=[Message(role=Role.USER, text="Count from 1 to 5, comma-separated.")],
            tools=[],
        )
    ):
        if isinstance(ev, ProviderTextDelta):
            print(ev.text, end="", flush=True)
        elif isinstance(ev, ProviderThinkingDelta):
            print(f"[think:{ev.text}]", end="", flush=True)
        elif isinstance(ev, ProviderCompleted):
            print(
                f"\n  done. usage={ev.usage} "
                f"tool_calls={[tc.name for tc in ev.message.tool_calls]}"
            )

    print("\n✅ 联调通过:provider 能与该端点正常 complete + 工具调用 + 流式。")


if __name__ == "__main__":
    asyncio.run(main())
