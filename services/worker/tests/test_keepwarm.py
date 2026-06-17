from unittest.mock import AsyncMock, MagicMock

from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.keepwarm import _ping, keepwarm_loop


def _settings(**over) -> WorkerSettings:
    base = dict(openai_api_key="k", keepwarm_enabled=True, keepwarm_model="M")
    base.update(over)
    return WorkerSettings(_env_file=None, **base)


async def test_keepwarm_disabled_returns_immediately():
    # 关闭即 no-op:直接返回,不进 while 循环(否则会卡住测试 = 验证守卫确实早返回)
    await keepwarm_loop(_settings(keepwarm_enabled=False))


async def test_keepwarm_no_platform_key_returns_immediately():
    # 没配平台 key(BYOK-only / 未配)→ 跳过保活,直接返回
    await keepwarm_loop(_settings(openai_api_key=""))


async def test_keepwarm_no_model_returns_immediately():
    await keepwarm_loop(_settings(keepwarm_model=""))


async def test_ping_sends_minimal_completion():
    # _ping 给指定模型发 max_tokens=1 的极小请求(焐热路由用)
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    await _ping(client, "DeepSeek-V4-Flash")
    client.chat.completions.create.assert_awaited_once()
    kwargs = client.chat.completions.create.await_args.kwargs
    assert kwargs["model"] == "DeepSeek-V4-Flash"
    assert kwargs["max_tokens"] == 1
    assert kwargs["messages"][0]["role"] == "user"
