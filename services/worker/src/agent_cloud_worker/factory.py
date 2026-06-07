from __future__ import annotations

from openai import AsyncOpenAI

from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.openai_provider import OpenAIProvider
from agent_cloud_worker.provider import Provider
from agent_cloud_worker.server import ProviderFactory


def build_provider_factory(settings: WorkerSettings) -> ProviderFactory:
    """造一个 provider_factory(model, provider, key_ref)->Provider。

    v1:所有 key_ref 共用 settings 里配置的单组 {api_key, base_url}(每 key_ref 选择 +
    KMS 留后续)。openai SDK 自带 timeout + max_retries(自动退避 429/5xx)。
    """

    def factory(model: str, provider: str, key_ref: str) -> Provider:
        if not settings.openai_api_key:
            raise RuntimeError(
                "OpenAI API key not configured (set AGENT_CLOUD_WORKER_OPENAI_API_KEY)"
            )
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
        return OpenAIProvider(
            client=client,
            model=model,
            max_tokens=settings.request_max_tokens,
            max_tokens_param=settings.max_tokens_param,
        )

    return factory
