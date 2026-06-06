from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from agent_cloud_backend.api import (
    agent_configs,
    agent_skills,
    context_documents,
    memory_entries,
    messages,
    sessions,
    skills,
    turn,
    users,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Agent Cloud Backend")

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_request: Request, _exc: IntegrityError) -> JSONResponse:
        # FK / unique / not-null violations are client errors. Return a generic
        # 409 instead of leaking the raw DB message (table/column/SQL) in a 500.
        # The request's DB session is closed by the get_session dependency's
        # context manager, discarding the aborted transaction.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "integrity constraint violation"},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (
        users,
        agent_configs,
        sessions,
        messages,
        context_documents,
        memory_entries,
        turn,
        skills,
        agent_skills,
    ):
        app.include_router(module.router)

    return app


app = create_app()
