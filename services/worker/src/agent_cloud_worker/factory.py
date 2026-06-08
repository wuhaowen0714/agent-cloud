from __future__ import annotations

from openai import AsyncOpenAI

from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.openai_provider import OpenAIProvider
from agent_cloud_worker.provider import Provider
from agent_cloud_worker.server import ProviderFactory


def _effective_credentials(
    settings: WorkerSettings, api_key: str, base_url: str
) -> tuple[str, str]:
    """BYO-Key:请求带 api_key 则用之(base_url 缺省回退全局);否则用全局 settings。"""
    if api_key:
        return api_key, base_url or settings.openai_base_url
    return settings.openai_api_key, settings.openai_base_url


def build_provider_factory(settings: WorkerSettings) -> ProviderFactory:
    """造 provider_factory(model, provider, api_key, base_url)->Provider。
    openai SDK 自带 timeout + max_retries(自动退避 429/5xx)。"""

    def factory(model: str, provider: str, api_key: str, base_url: str) -> Provider:
        eff_key, eff_base = _effective_credentials(settings, api_key, base_url)
        if not eff_key:
            raise RuntimeError(
                "no API key (set AGENT_CLOUD_WORKER_OPENAI_API_KEY or attach a credential)"
            )
        client = AsyncOpenAI(
            api_key=eff_key,
            base_url=eff_base,
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
