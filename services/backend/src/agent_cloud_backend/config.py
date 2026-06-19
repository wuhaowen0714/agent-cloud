from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CLOUD_", env_file=".env")

    # 形如 postgresql+asyncpg://user:pass@host:5432/dbname
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud"

    worker_endpoint: str = "localhost:50052"
    sandbox_base_root: str = "/tmp/agent-cloud-sandboxes"
    object_store_root: str = "/tmp/agent-cloud-object-store"
    allow_uploaded_archives: bool = False

    # 回合进行中每隔这么多秒续租会话锁(必须远小于 try_acquire 的 600s lease)
    session_heartbeat_seconds: int = 200

    # ── 沙箱 provisioner(spec: docker-sandbox-provisioner-design)──
    sandbox_provisioner: str = "inprocess"  # inprocess | docker
    sandbox_host_root: str = ""  # DooD 下宿主 workspace 根;空=回退 sandbox_base_root
    sandbox_image: str = "agent-cloud-sandbox:latest"
    sandbox_docker_network_mode: str = "publish"  # publish(dev) | network(prod)
    # network 模式必填:worker 容器名,backend 在 spawn 时把它接入每个沙箱专属网络(spec B)
    sandbox_worker_container: str = ""
    sandbox_mem_limit: str = "512m"
    sandbox_nano_cpus: int = 1_000_000_000  # 1 vCPU
    sandbox_pids_limit: int = 256
    sandbox_allow_net: bool = True
    sandbox_idle_ttl_seconds: int = 1800
    sandbox_reap_interval_seconds: int = 120
    # 沙箱容器系统时区(注入 TZ env;镜像已含 tzdata)。默认北京,与 worker 注入的"今天日期"
    # (timezone_offset_hours 默认 +8)对齐,避免 agent 在沙箱里 `date` 读到 UTC 误判当前时刻。
    sandbox_timezone: str = "Asia/Shanghai"

    # 文件管理:单文件上传上限(字节)。超出 → 413。
    file_upload_max_bytes: int = 100 * 1024 * 1024

    # 会话压缩(spec §11):回合后用模型返回的真实 context_tokens 判阈值,超此则折叠历史。
    compaction_token_threshold: int = 128000  # 全局默认(未配置窗口/覆盖的模型用它)
    # 按模型显式覆盖阈值(模型名 → 阈值);优先级最高。
    # 经环境变量配置(JSON):AGENT_CLOUD_COMPACTION_TOKEN_THRESHOLDS='{"DeepSeek-V4-Pro": 200000}'。
    compaction_token_thresholds: dict[str, int] = {}
    # 模型上下文窗口(tokens):无显式覆盖时,阈值 = 窗口 × compaction_trigger_ratio。
    model_context_windows: dict[str, int] = {
        "DeepSeek-V4-Pro": 1_000_000,
        "DeepSeek-V4-Flash": 1_000_000,
        "GLM-5.1": 200_000,
    }
    compaction_trigger_ratio: float = 0.75  # 上下文占用到窗口的 75% 触发自动压缩
    compaction_keep_recent: int = 8  # 压缩时保留逐字的最近消息条数

    # 回合失败透明自动重试(spec: turn-recovery-auto-retry)
    turn_max_overflow_retries: int = 2  # 超窗压缩重试上限
    turn_max_transient_retries: int = 3  # 瞬时错误退避重试上限
    turn_max_total_attempts: int = 6  # 1 首发 + 两类上限之和;纯兜底
    turn_retry_backoff_base_seconds: float = 0.5  # 第 i 次重试等 base*2**i 秒,单步封顶 8s

    # 鉴权(spec: auth-multitenancy)
    # HS256 签名密钥;prod 必须经 env 覆盖。默认 ≥32B 仅为消除 JWT 短密钥警告,非安全值。
    auth_secret: str = "dev-insecure-secret-change-me-in-production-0123456789"
    access_token_ttl_seconds: int = 900  # access JWT 有效期 15min
    refresh_token_ttl_seconds: int = 2592000  # refresh 有效期 30d
    auth_cookie_name: str = "ac_refresh"  # refresh 的 httpOnly cookie 名
    auth_cookie_secure: bool = False  # 本地 http=false;prod(https)必须 true

    # BYO-Key:凭据 AES-GCM 主密钥(base64 编码的 32 字节);空 = 凭据功能不可用。
    # 生成:python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
    credential_key: str = ""

    # 智能体记忆(spec 2026-06-09:自整合单块)。
    memory_soft_chars: int = 2000  # 每块软上限,仅引导 LLM,后端不硬截断
    memory_min_rounds: int = 10  # 空闲提炼:自上次提炼以来新对话轮次 ≥ 此值才提
    memory_idle_seconds: int = 1800  # 空闲多久算"可提炼"(默认同沙箱 idle TTL)
    memory_max_versions: int = 20  # 每块保留版本数,超出裁剪

    # 平台(sophnet)可选模型清单 + 新建 session 的默认模型(session 选 sophnet 时的 model 候选;
    # BYOK provider 的模型走用户 credential.models)。env 覆盖走 JSON:
    # AGENT_CLOUD_PLATFORM_MODELS='["DeepSeek-V4-Pro","GLM-5.1"]'。
    platform_models: list[str] = ["DeepSeek-V4-Pro", "DeepSeek-V4-Flash", "GLM-5.1"]
    default_model: str = "DeepSeek-V4-Pro"
    # 支持图片输入(vision/多模态)的平台模型清单。上传图片问答需 vision 模型;非 vision 模型
    # 收到图片由前端拦截提示切换(spec: image-understanding)。仿 model_context_windows 模式,
    # env JSON 覆盖:AGENT_CLOUD_VISION_MODELS='["Kimi-K2.6"]'。BYOK 模型的 vision 走凭据标记。
    vision_models: list[str] = ["Kimi-K2.6"]

    def resolve_default_model(self) -> str:
        """新建 session 的默认模型;default_model 须 ∈ platform_models,否则取首个(空清单兜底)。"""
        if self.default_model in self.platform_models:
            return self.default_model
        return self.platform_models[0] if self.platform_models else "DeepSeek-V4-Pro"

    def is_vision_model(self, model: str) -> bool:
        """该平台模型是否支持图片输入。BYOK 模型的 vision 由凭据标记决定,不走这里。"""
        return model in self.vision_models

    # ── 定时任务(spec 2026-06-13-scheduled-tasks)──
    scheduler_enabled: bool = True  # 进程内轮询器开关(多副本可全开,SKIP LOCKED 防重复触发)
    scheduler_poll_interval_seconds: int = 30  # 轮询周期(子分钟精度无必要)
    scheduler_batch_size: int = 10  # 单轮最多取多少到期任务
    scheduler_run_lease_seconds: int = 900  # running_since 租约:超时即视崩溃残留可重取
    scheduler_max_concurrent_runs: int = 4  # 单轮并发执行回合上限

    def compaction_threshold_for(self, model: str) -> int:
        """该模型的压缩阈值,三级解析:显式覆盖 → 窗口 × ratio → 全局默认。"""
        if model in self.compaction_token_thresholds:
            return self.compaction_token_thresholds[model]
        if model in self.model_context_windows:
            return int(self.model_context_windows[model] * self.compaction_trigger_ratio)
        return self.compaction_token_threshold

    @property
    def effective_sandbox_host_root(self) -> str:
        return self.sandbox_host_root or self.sandbox_base_root


def get_settings() -> Settings:
    return Settings()
