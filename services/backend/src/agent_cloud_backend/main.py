from fastapi import FastAPI

from agent_cloud_backend.api import (
    agent_configs,
    context_documents,
    memory_entries,
    messages,
    sessions,
    users,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Agent Cloud Backend")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (users, agent_configs, sessions, messages, context_documents, memory_entries):
        app.include_router(module.router)

    return app


app = create_app()
