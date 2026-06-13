import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_agent
from agent_cloud_backend.models.scheduled_task import ScheduledTask
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.scheduled_task import ScheduledTaskRepository
from agent_cloud_backend.scheduler import schedule
from agent_cloud_backend.scheduler.schedule import ScheduleError
from agent_cloud_backend.schemas.scheduled_task import (
    ScheduledTaskCreate,
    ScheduledTaskRead,
    ScheduledTaskUpdate,
)

router = APIRouter(prefix="/scheduled-tasks", tags=["scheduled-tasks"])


def _normalize_or_422(kind: str, expr: str, tz: str) -> str:
    try:
        return schedule.validate_and_normalize(kind, expr, tz)
    except ScheduleError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("", response_model=list[ScheduledTaskRead])
async def list_tasks(
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)
):
    return await ScheduledTaskRepository(session).list_by_user(user.id)


@router.post("", response_model=ScheduledTaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: ScheduledTaskCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await owned_agent(body.agent_config_id, user.id, session)  # 不属本人 → 404
    norm = _normalize_or_422(body.schedule_kind, body.schedule_expr, body.schedule_tz)
    next_run = schedule.first_run_at(body.schedule_kind, norm, body.schedule_tz, datetime.now(UTC))
    t = ScheduledTask(
        user_id=user.id,
        agent_config_id=body.agent_config_id,
        name=body.name,
        prompt=body.prompt,
        schedule_kind=body.schedule_kind,
        schedule_expr=norm,
        schedule_tz=body.schedule_tz,
        next_run_at=next_run,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t


@router.patch("/{task_id}", response_model=ScheduledTaskRead)
async def update_task(
    task_id: uuid.UUID,
    body: ScheduledTaskUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    repo = ScheduledTaskRepository(session)
    t = await repo.get_owned(task_id, user.id)
    if t is None:
        raise HTTPException(status_code=404, detail="scheduled task not found")
    data = body.model_dump(exclude_unset=True)
    schedule_changed = any(k in data for k in ("schedule_kind", "schedule_expr", "schedule_tz"))
    for k, v in data.items():
        setattr(t, k, v)
    if schedule_changed:
        t.schedule_expr = _normalize_or_422(t.schedule_kind, t.schedule_expr, t.schedule_tz)
    # 改了排期、或刚被(重新)启用 → 重算下次触发(暂停 enabled=False 时 due 查询已会跳过)
    if (schedule_changed or data.get("enabled") is True) and t.enabled:
        t.next_run_at = schedule.first_run_at(
            t.schedule_kind, t.schedule_expr, t.schedule_tz, datetime.now(UTC)
        )
    await session.commit()
    await session.refresh(t)
    return t


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    repo = ScheduledTaskRepository(session)
    t = await repo.get_owned(task_id, user.id)
    if t is None:
        raise HTTPException(status_code=404, detail="scheduled task not found")
    await repo.delete(t)
    await session.commit()


@router.post("/{task_id}/run-now", response_model=ScheduledTaskRead)
async def run_now(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    repo = ScheduledTaskRepository(session)
    t = await repo.get_owned(task_id, user.id)
    if t is None:
        raise HTTPException(status_code=404, detail="scheduled task not found")
    t.enabled = True
    t.next_run_at = datetime.now(UTC)  # 立即到期 → 轮询器 ≤1 周期内拾取(单一执行路径)
    await session.commit()
    await session.refresh(t)
    return t
