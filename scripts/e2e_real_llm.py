"""全栈端到端联调:用真实 OpenAI 兼容端点跑一个完整回合。

链路:后端 SSE 端点 -> worker(真 OpenAIProvider) -> 真 LLM -> agent 决定调
write_file/read_file/bash -> 沙箱执行 -> 结果回填 -> 收尾落库。

复用已验证的进程内全栈装配(testcontainer Postgres + 进程内 backend ASGI +
进程内 worker gRPC + 进程内 sandbox),只把 FakeProvider 换成真实 OpenAIProvider。
你零额外搭建——只要设密钥就能跑(Postgres 由 testcontainers 自动起,故需要 Docker)。

用法(推荐 .env):
    1) 在仓库根建 .env(参考 .env.example,已被 gitignore):
         AGENT_CLOUD_WORKER_OPENAI_API_KEY=你的key
         AGENT_CLOUD_WORKER_OPENAI_BASE_URL=https://你的端点/v1
         # 推理模型(o 系列/gpt-5)才需要 MAX_TOKENS_PARAM,详见 .env.example
    2) cd /Users/wuhaowen/src/llm-agent/agent-cloud/services/backend
       uv run python ../../scripts/e2e_real_llm.py "你的模型名"

脚本会自动读仓库根 .env、并自动设 TESTCONTAINERS_RYUK_DISABLED=true。也可以不用 .env、
直接 export 这些环境变量(export 的优先级更高)。
注意:必须从 services/backend 目录用 uv run 跑(那里才有 testcontainers / worker /
sandbox 依赖);需要本机 Docker(Postgres 由 testcontainers 自动起)。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv

# 从仓库根的 .env 读凭据(已被 gitignore);override=False 让显式 export 的环境变量优先。
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
# 本机 Docker 必须禁用 Ryuk(否则 testcontainers 的 Postgres 会被中途回收挂住);自动设好。
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

PROMPT = (
    "Use the write_file tool to create a file named notes.txt containing exactly "
    "'hello from the agent', then use the read_file tool to read it back, and finally "
    "tell me what the file contains."
)


async def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else ""
    if not model:
        print("用法: uv run python scripts/e2e_real_llm.py <model>")
        sys.exit(2)

    from agent_cloud_worker.config import get_worker_settings

    wsettings = get_worker_settings()
    print(
        f"endpoint={wsettings.openai_base_url}  model={model}  "
        f"max_tokens_param={wsettings.max_tokens_param}  "
        f"api_key={'set' if wsettings.openai_api_key else 'MISSING'}"
    )
    if not wsettings.openai_api_key:
        print("ERROR: export AGENT_CLOUD_WORKER_OPENAI_API_KEY")
        sys.exit(1)

    import agent_cloud_backend.db as db_module
    from agent_cloud_backend.api.deps import get_session
    from agent_cloud_backend.config import Settings, get_settings
    from agent_cloud_backend.main import create_app
    from agent_cloud_backend.models import Base
    from agent_cloud_backend.sandbox.deps import get_sandbox_manager
    from agent_cloud_backend.sandbox.inprocess import InProcessProvisioner
    from agent_cloud_backend.sandbox.manager import SandboxManager
    from agent_cloud_worker.factory import build_provider_factory
    from agent_cloud_worker.server import create_server as create_worker_server
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from testcontainers.postgres import PostgresContainer

    factory = build_provider_factory(wsettings)
    worker_server, wport = await create_worker_server(provider_factory=factory, port=0)
    print(f"worker gRPC listening on localhost:{wport}")

    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        engine = create_async_engine(pg.get_connection_url(), future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        db_module._sessionmaker = maker  # 流式生成器 / 心跳走全局 sessionmaker

        tmp = Path(tempfile.mkdtemp(prefix="ac-e2e-"))
        provisioner = InProcessProvisioner(base_root=tmp)
        manager = SandboxManager(provisioner=provisioner, sessionmaker=maker)

        async def _override_session():
            async with maker() as s:
                yield s

        app = create_app()
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[get_settings] = lambda: Settings(
            worker_endpoint=f"localhost:{wport}",
            sandbox_base_root=str(tmp),
            object_store_root=str(tmp / "obj"),
        )
        app.dependency_overrides[get_sandbox_manager] = lambda: manager

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", timeout=180.0
            ) as c:
                uid = (await c.post("/users", json={"email": f"{uuid.uuid4()}@e.com"})).json()["id"]
                aid = (
                    await c.post(
                        "/agent-configs",
                        json={"user_id": uid, "name": "demo", "model": model, "provider": "openai"},
                    )
                ).json()["id"]
                sid = (
                    await c.post("/sessions", json={"user_id": uid, "agent_config_id": aid})
                ).json()["id"]
                print(f"user={uid}\nagent={aid}\nsession={sid}\n\n--- streaming turn ---")

                async with c.stream(
                    "POST",
                    f"/sessions/{sid}/turn/stream",
                    json={"content": PROMPT},
                ) as resp:
                    if resp.status_code != 200:
                        print(f"[HTTP {resp.status_code}] {await resp.aread()}")
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        ev = json.loads(line[len("data:") :].strip())
                        t = ev.get("type")
                        if t == "thinking_delta":
                            print(f"\033[2m{ev['text']}\033[0m", end="", flush=True)
                        elif t == "text_delta":
                            print(ev["text"], end="", flush=True)
                        elif t == "tool_call_start":
                            print(f"\n  [tool→] {ev['tool']}({ev['args']})")
                        elif t == "tool_result":
                            print(f"  [tool←] is_error={ev['is_error']}  {ev['result'][:300]}")
                        elif t == "turn_done":
                            print(
                                f"\n  [done] stop={ev['stop_reason']}  usage={ev['usage']}  "
                                f"msg_ids={ev['message_ids']}"
                            )
                        elif t == "error":
                            print(f"\n  [ERROR] {ev}")

                print("\n--- persisted messages (落库) ---")
                for m in (await c.get(f"/sessions/{sid}/messages")).json():
                    body = json.dumps(m["content"], ensure_ascii=False)
                    print(f"  {m['role']}: {body[:300]}")

                f = tmp / uid / "sessions" / sid / "notes.txt"
                print(
                    f"\nsandbox file {f}:\n  "
                    + (f"EXISTS -> {f.read_text()!r}" if f.is_file() else "MISSING")
                )
        finally:
            app.dependency_overrides.clear()
            await provisioner.stop_all()
            await engine.dispose()
            await worker_server.stop(None)

    print("\n✅ 全栈端到端联调完成。")


if __name__ == "__main__":
    asyncio.run(main())
