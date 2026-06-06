from __future__ import annotations

from pathlib import Path

from agent_cloud_backend.config import get_settings
from agent_cloud_backend.skills.store import LocalObjectStore, ObjectStore

_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _store
    if _store is None:
        _store = LocalObjectStore(Path(get_settings().object_store_root))
    return _store


def get_skill_registry_root() -> Path:
    # 内置 registry 随包发布:src/agent_cloud_backend/skill_registry/
    return Path(__file__).resolve().parent.parent / "skill_registry"
