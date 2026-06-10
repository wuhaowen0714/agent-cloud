from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CLOUD_WORKER_", env_file=".env")

    grpc_host: str = "0.0.0.0"
    grpc_port: int = 50052

    # OpenAI 兼容端点凭据(v1:单组,所有 agent 共用;每 key_ref 选择 + KMS 留后续)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 60.0
    openai_max_retries: int = 2

    # 单次请求输出上限。撞上限(finish_reason=length)有兜底:文本截断会落库提示、
    # 工具参数截断会回合内自修复(见 loop/_TRUNCATED_CALL_RESULT),但上限给足更省事。
    request_max_tokens: int = 32768
    # 经典 chat completions 用 "max_tokens";OpenAI 推理模型(o 系列 / gpt-5)要
    # "max_completion_tokens"。多数兼容端点(vLLM/OpenRouter)用 max_tokens,故默认它;
    # 接 OpenAI 推理模型时把本项设为 "max_completion_tokens"。
    max_tokens_param: str = "max_tokens"


def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
