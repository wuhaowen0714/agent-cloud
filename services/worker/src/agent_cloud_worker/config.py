from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_cloud_worker.image_gen import (
    DEFAULT_IMAGE_EDIT_MODEL,
    DEFAULT_IMAGE_ENDPOINT,
    DEFAULT_IMAGE_MODEL,
)
from agent_cloud_worker.web_search import DEFAULT_SEARCH_ENDPOINT


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

    # 单个回合内 LLM↔工具往返的迭代上限。跑满即 stop_reason="max_iterations" 收尾(回合不完整,
    # 由后端 best-effort 处理)。调大 → 允许更长的自主链路,但最坏耗时/输出预算按倍数上升。
    max_iterations: int = 20

    # 注入 system prompt 的"今天日期"用的固定时区偏移(小时,不含夏令时)。默认 +8(北京):
    # worker 取此时区当前日期告诉模型,解决模型不知"今天/今年"查时事瞎猜。范围 (-24, 24)——越界
    # 启动即 fail-fast(否则每回合 timezone() 抛错被误判成客户端错误)。海外部署按当地改
    # (⚠️ DST 地区如美西在夏令时期会差 1 小时,跨午夜窗口可能差一天)。
    timezone_offset_hours: float = Field(default=8.0, gt=-24, lt=24)

    # Agent 所在网络区域,决定是否向 system prompt 注入"哪些站点不可达"的提示。
    # "cn" 或阿里云 region id("cn-hangzhou" 等)=中国大陆:注入(首选 cn.bing.com 搜索,
    # 避开 google/wikipedia/百度验证码等,失败即换);留空或其它值=不注入(海外/无限制部署)。
    # 默认 cn:生产部署在阿里云境内。
    network_region: str = "cn"

    # web_search 工具(worker 原生):**独立于 LLM key** 的专用搜索凭据。配了 api_key 才把工具
    # 暴露给模型(空 = 不暴露,海外/未接搜索后端时优雅降级)。端点是 sophnet moltbot;LLM 可能
    # BYOK 成别家模型,其 key 对此端点无效,故搜索用平台专用 key,绝不复用 LLM key。
    web_search_api_key: str = ""
    web_search_endpoint: str = DEFAULT_SEARCH_ENDPOINT
    web_search_max_results: int = 8

    # generate_image 工具(worker 原生):文生图,图片落盘到工作区 media/picture/。同 web_search
    # 用独立于 LLM 的专用 key。留空则回退 web_search_api_key(同一 sophnet 平台 key,见 __main__);
    # 两者都空 = 不暴露 generate_image。endpoint 是 sophnet 图片生成异步任务端点。
    image_gen_api_key: str = ""
    image_gen_endpoint: str = DEFAULT_IMAGE_ENDPOINT
    image_gen_model: str = DEFAULT_IMAGE_MODEL
    # edit_image 工具(图生图/编辑):同 image_gen 的 key/端点,只换 Edit 模型。
    image_edit_model: str = DEFAULT_IMAGE_EDIT_MODEL


def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
