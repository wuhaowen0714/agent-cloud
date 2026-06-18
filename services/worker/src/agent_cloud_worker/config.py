import json
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    # 单次请求超时:LLM 端点偶发"首 token 卡住"(连接正常但久不吐字,2026-06-13 实测 sophnet
    # 间歇性 ~60s 不响应,连接 0.03s 没问题→非网络)。超时即被 SDK 重试,但卡满超时才重试,
    # 用户感知"卡住不答"。压到 45s:健康首 token(含大上下文 prefill)远低于此、不误杀,卡住
    # 时早 15s 重试。多 1 次重试(2→3)多一次甩开间歇性卡顿的机会。两者皆可经 env 覆盖。
    openai_timeout_seconds: float = 45.0
    openai_max_retries: int = 3

    # LLM 路由保活:sophnet 对 idle 客户端冷启,首请求久不吐字(实测间歇性 ~60s,见上)。后台
    # 每隔 keepwarm_interval_seconds 给每个平台模型发个 max_tokens=1 的小请求,把 sophnet 上游
    # 路由一直焐着热的。⚠️ 冷启是**按模型**的:2026-06-18 线上抓到——keepwarm 只焐 Flash 时其
    # 心跳全程 1-4s(热),但用户切 DeepSeek-V4-Pro 的首条仍冷到卡满 45s 超时再重试(~47s)。所以
    # 必须焐**全部** platform_models、不能只焐一个。仅平台 key(BYOK 会话各自端点不在此列);单个
    # 模型 ping 失败只记日志、不影响 worker 主流程与同批其它模型。
    keepwarm_enabled: bool = True
    keepwarm_interval_seconds: float = 60.0  # 实测 sophnet 5min 内就凉(300s 时每个 ping 都撞冷)
    # 焐全部平台模型,须与 backend platform_models 对齐;平台模型变更时改这里或经 env 覆盖。env 覆盖
    # 接受 JSON 数组 '["A","B"]'、逗号分隔 'A,B' 或单个裸词 'A'(见下方 validator,容错运维直觉、
    # 不让坏格式 crash 整个 worker)。NoDecode 关掉 pydantic 源层 JSON 解码,改由 validator 自己解析。
    keepwarm_models: Annotated[list[str], NoDecode] = [
        "DeepSeek-V4-Pro",
        "DeepSeek-V4-Flash",
        "GLM-5.1",
    ]
    keepwarm_timeout_seconds: float = 120.0  # 冷 ping ~60s,要 >60s 才跑得完真正焐热(否则卡边界超时)
    # 某轮有模型 ping 失败(撞 sophnet 慢窗口)后,下一轮改用这个短间隔尽快重焐(而非等满 interval),
    # 把路由"凉着"的暴露窗口压短;全成功才回正常 interval。只缩短 sophnet 恢复后的重焐延迟,治标。
    keepwarm_retry_interval_seconds: float = 5.0

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

    @field_validator("keepwarm_models", mode="before")
    @classmethod
    def _parse_keepwarm_models(cls, v: object) -> object:
        """env 覆盖容错:接受 JSON 数组、逗号分隔、单个裸词、空串;坏格式不再 crash worker。

        默认值(直接传 list)与 init 传 list 原样放行;只对 env 来的 str 做解析。
        """
        if not isinstance(v, str):
            return v
        s = v.strip()
        if not s:
            return []
        if s.startswith("["):
            return json.loads(s)  # JSON 数组;格式真错才抛,属显式误用
        return [m.strip() for m in s.split(",") if m.strip()]


def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
