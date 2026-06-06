"""Regression: agent-cloud-common must declare protobuf as a *runtime* dep.

The generated gRPC stubs (`agent_cloud.v1.sandbox_pb2`) `import google.protobuf`
at import time. protobuf was previously present only transitively via the dev
dep grpcio-tools, so a runtime-only install (or a bare `uv sync` that prunes the
dev group) would break the stubs. Lock protobuf into common's declared runtime
dependencies.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

# tests/ -> sandbox/ -> services/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMMON_PYPROJECT = _REPO_ROOT / "packages" / "common" / "pyproject.toml"


def test_common_declares_protobuf_runtime_dep():
    data = tomllib.loads(_COMMON_PYPROJECT.read_text())
    deps = data["project"]["dependencies"]
    names = {dep.split()[0].split(">")[0].split("=")[0].split("<")[0] for dep in deps}
    assert "protobuf" in names, f"protobuf must be a runtime dep of common; got {deps}"


def test_generated_stubs_import_protobuf_at_runtime():
    # The actual runtime contract the dep exists to satisfy.
    import google.protobuf  # noqa: F401
    from agent_cloud.v1 import sandbox_pb2  # noqa: F401
