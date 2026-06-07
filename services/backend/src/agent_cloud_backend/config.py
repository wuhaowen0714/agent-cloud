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

    @property
    def effective_sandbox_host_root(self) -> str:
        return self.sandbox_host_root or self.sandbox_base_root


def get_settings() -> Settings:
    return Settings()
