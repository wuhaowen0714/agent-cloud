import pytest
from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.factory import build_provider_factory
from agent_cloud_worker.openai_provider import OpenAIProvider


def test_factory_builds_openai_provider():
    settings = WorkerSettings(openai_api_key="sk-x", openai_base_url="http://ep/v1")
    factory = build_provider_factory(settings)
    provider = factory("gpt-x", "openai", "ref-1")
    assert isinstance(provider, OpenAIProvider)
    assert provider._model == "gpt-x"
    # client 用配置的 base_url(AsyncOpenAI 暴露 .base_url)
    assert str(provider._client.base_url).rstrip("/").endswith("/v1")


def test_factory_missing_api_key_raises():
    factory = build_provider_factory(WorkerSettings(openai_api_key=""))
    with pytest.raises(RuntimeError, match="API key"):
        factory("m", "openai", "ref")
