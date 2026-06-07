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


def get_settings() -> Settings:
    return Settings()
