import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.keepwarm import _ping, _warm_all, _warm_one, keepwarm_loop


def _settings(**over) -> WorkerSettings:
    base = dict(openai_api_key="k", keepwarm_enabled=True, keepwarm_models=["M"])
    base.update(over)
    return WorkerSettings(_env_file=None, **base)


async def test_keepwarm_disabled_returns_immediately():
    # 关闭即 no-op:直接返回,不进 while 循环(否则会卡住测试 = 验证守卫确实早返回)
    await keepwarm_loop(_settings(keepwarm_enabled=False))


async def test_keepwarm_no_platform_key_returns_immediately():
    # 没配平台 key(BYOK-only / 未配)→ 跳过保活,直接返回
    await keepwarm_loop(_settings(openai_api_key=""))


async def test_keepwarm_no_models_returns_immediately():
    # 没配任何模型 → 跳过保活,直接返回(空清单守卫)
    await keepwarm_loop(_settings(keepwarm_models=[]))


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


async def test_warm_all_pings_every_model():
    # 本次修复核心:冷启按模型,_warm_all 必须把 keepwarm_models 里**每个**模型都焐到
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    failed = await _warm_all(client, ["DeepSeek-V4-Pro", "DeepSeek-V4-Flash", "GLM-5.1"])
    assert failed == 0  # 全成功 → 失败数 0
    assert client.chat.completions.create.await_count == 3
    called = {c.kwargs["model"] for c in client.chat.completions.create.await_args_list}
    assert called == {"DeepSeek-V4-Pro", "DeepSeek-V4-Flash", "GLM-5.1"}


async def test_warm_one_returns_true_on_success():
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    assert await _warm_one(client, "DeepSeek-V4-Pro") is True


async def test_warm_one_swallows_ping_failure_and_returns_false():
    # 单模型 ping 失败不外抛(否则 gather 带垮同批其它模型),且返回 False 供循环判断
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
    assert await _warm_one(client, "DeepSeek-V4-Pro") is False


async def test_warm_all_isolates_one_failing_model_and_counts_it():
    # 一个模型挂掉,其它模型照常被 ping(失败隔离);_warm_all 返回失败数 1
    client = MagicMock()

    async def _create(*, model, **_):
        if model == "GLM-5.1":
            raise RuntimeError("cold")

    client.chat.completions.create = AsyncMock(side_effect=_create)
    failed = await _warm_all(client, ["DeepSeek-V4-Pro", "DeepSeek-V4-Flash", "GLM-5.1"])
    assert failed == 1
    assert client.chat.completions.create.await_count == 3


async def test_loop_fast_retries_after_failed_round(monkeypatch):
    # 失败轮(_warm_all 返回 >0)后用 retry_interval 尽快重焐;成功轮(返回 0)后用正常 interval
    from agent_cloud_worker import keepwarm as kw

    sleeps: list[float] = []
    results = iter([2, 0])  # 第1轮 2 个失败 → retry;第2轮全成功 → interval

    async def fake_warm_all(client, models):
        return next(results)

    async def fake_sleep(secs):
        sleeps.append(secs)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError  # 跑完两轮就停

    monkeypatch.setattr(kw, "_warm_all", fake_warm_all)
    monkeypatch.setattr(kw.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await keepwarm_loop(
            _settings(keepwarm_interval_seconds=60.0, keepwarm_retry_interval_seconds=5.0)
        )
    assert sleeps == [5.0, 60.0]  # 失败轮→5s retry,成功轮→60s interval


def test_keepwarm_models_parses_json_array():
    # env 覆盖容错:JSON 数组
    assert _settings(keepwarm_models='["A", "B"]').keepwarm_models == ["A", "B"]


def test_keepwarm_models_parses_comma_separated():
    # env 覆盖容错:运维直觉的逗号分隔(原本会 SettingsError crash worker,现归一成 list)
    assert _settings(keepwarm_models="A, B ,C").keepwarm_models == ["A", "B", "C"]


def test_keepwarm_models_parses_bare_word_and_empty():
    # 单个裸词 → 单元素;空串 → 空清单(触发 loop 的"无模型"守卫,而非 crash)
    assert _settings(keepwarm_models="Solo").keepwarm_models == ["Solo"]
    assert _settings(keepwarm_models="  ").keepwarm_models == []


def test_keepwarm_models_passes_list_through():
    # 直接传 list(默认值 / init)原样放行,不被当字符串解析
    assert _settings(keepwarm_models=["X", "Y"]).keepwarm_models == ["X", "Y"]
