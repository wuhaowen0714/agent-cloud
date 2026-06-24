import pytest
from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.factory import _effective_credentials, build_provider_factory
from agent_cloud_worker.openai_provider import OpenAIProvider


def test_factory_builds_openai_provider():
    settings = WorkerSettings(openai_api_key="sk-x", openai_base_url="http://ep/v1")
    factory = build_provider_factory(settings)
    provider = factory("gpt-x", "openai", "", "")  # 无 per-request key → 用全局
    assert isinstance(provider, OpenAIProvider)
    assert provider._model == "gpt-x"
    # client 用配置的 base_url(AsyncOpenAI 暴露 .base_url)
    assert str(provider._client.base_url).rstrip("/").endswith("/v1")


def test_factory_missing_api_key_raises():
    factory = build_provider_factory(WorkerSettings(openai_api_key=""))
    with pytest.raises(RuntimeError, match="API key"):
        factory("m", "openai", "", "")


def test_per_request_key_overrides_global():
    s = WorkerSettings(openai_api_key="GLOBAL", openai_base_url="https://global/v1")
    key, base = _effective_credentials(s, "sk-user", "https://user/v1")
    assert key == "sk-user" and base == "https://user/v1"


def test_per_request_key_without_base_url_falls_back_to_global_base():
    s = WorkerSettings(openai_api_key="GLOBAL", openai_base_url="https://global/v1")
    key, base = _effective_credentials(s, "sk-user", "")
    assert key == "sk-user" and base == "https://global/v1"


def test_no_request_key_uses_global():
    s = WorkerSettings(openai_api_key="GLOBAL", openai_base_url="https://global/v1")
    key, base = _effective_credentials(s, "", "")
    assert key == "GLOBAL" and base == "https://global/v1"


def test_per_request_key_actually_used_by_client():
    s = WorkerSettings(openai_api_key="GLOBAL", openai_base_url="https://global/v1")
    provider = build_provider_factory(s)("m", "openai", "sk-user", "https://user/v1")
    assert provider._client.api_key == "sk-user"
    assert str(provider._client.base_url).rstrip("/") == "https://user/v1"


def test_factory_wires_ttft_config_from_settings():
    # wiring:factory 把 settings 的 ttft 参数真传给 provider(防"漏传参→配置静默失效")。
    # 改非默认值再断言 provider 用的是这些值,而非常量默认。
    s = WorkerSettings(
        openai_api_key="sk-x",
        ttft_text_base_seconds=7.0,
        ttft_multimodal_base_seconds=19.0,
        ttft_ceil_seconds=33.0,
    )
    provider = build_provider_factory(s)("m", "openai", "", "")
    assert provider._ttft is not None
    assert provider._ttft.text_base == 7.0
    assert provider._ttft.multimodal_base == 19.0
    assert provider._ttft.ceil == 33.0
