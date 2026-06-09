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
    sandbox_docker_network: str = "agent-cloud-net"
    sandbox_mem_limit: str = "512m"
    sandbox_nano_cpus: int = 1_000_000_000  # 1 vCPU
    sandbox_pids_limit: int = 256
    sandbox_allow_net: bool = True
    sandbox_idle_ttl_seconds: int = 1800
    sandbox_reap_interval_seconds: int = 120

    # 文件管理:单文件上传上限(字节)。超出 → 413。
    file_upload_max_bytes: int = 100 * 1024 * 1024

    # 会话压缩(spec §11):回合后用模型返回的真实 context_tokens 判阈值,超此则折叠历史。
    compaction_token_threshold: int = 128000  # 全局默认(建议设为所用模型 window 的 ~70-80%)
    # 按模型覆盖阈值(模型名 → 阈值);未列出的模型回退 compaction_token_threshold。
    # 经环境变量配置(JSON):AGENT_CLOUD_COMPACTION_TOKEN_THRESHOLDS='{"DeepSeek-V4-Pro": 200000}'。
    compaction_token_thresholds: dict[str, int] = {}
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

    def compaction_threshold_for(self, model: str) -> int:
        """该模型的压缩阈值:优先 per-model 覆盖,否则回退全局默认。"""
        return self.compaction_token_thresholds.get(model, self.compaction_token_threshold)

    @property
    def effective_sandbox_host_root(self) -> str:
        return self.sandbox_host_root or self.sandbox_base_root


def get_settings() -> Settings:
    return Settings()
