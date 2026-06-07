from agent_cloud_backend.config import get_settings

from .store import FileStore, LocalFileStore


def get_file_store() -> FileStore:
    return LocalFileStore(get_settings().effective_sandbox_host_root)
