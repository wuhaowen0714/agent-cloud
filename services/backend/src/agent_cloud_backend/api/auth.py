from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.auth import security
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.refresh_token import RefreshTokenRepository
from agent_cloud_backend.repositories.user import UserRepository
from agent_cloud_backend.schemas.auth import LoginBody, RegisterBody, TokenResponse
from agent_cloud_backend.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(resp: Response, plain: str, settings: Settings) -> None:
    # cookie path = "/":浏览器按【请求 URL 的 path】做 cookie 匹配,而前端经代理访问
    # /api/auth/refresh(代理再 rewrite 去掉 /api 才打到后端 /auth/refresh)。若把 path 收窄成
    # "/auth",浏览器对 /api/auth/* 的请求就不会带上该 cookie → refresh/logout 静默失效。
    # 故用 "/"(配合 httpOnly + SameSite=Lax 仍安全),对前端的代理布局解耦。
    resp.set_cookie(
        key=settings.auth_cookie_name,
        value=plain,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


async def _issue(resp: Response, user: User, db: AsyncSession, settings: Settings) -> TokenResponse:
    """签发 refresh(存哈希 + set cookie)+ access(body),并 commit 本事务。"""
    plain, token_hash = security.new_refresh_token()
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds)
    await RefreshTokenRepository(db).issue(user.id, token_hash, expires_at)
    await db.commit()
    _set_refresh_cookie(resp, plain, settings)
    access = security.create_access_token(
        str(user.id), secret=settings.auth_secret, ttl_seconds=settings.access_token_ttl_seconds
    )
    return TokenResponse(access_token=access, user=UserRead.model_validate(user))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterBody,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    repo = UserRepository(db)
    if await repo.get_by_email(body.email) is not None:
        raise HTTPException(status_code=409, detail="email already registered")
    user = await repo.create(
        User(email=body.email, password_hash=security.hash_password(body.password))
    )
    return await _issue(response, user, db, settings)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginBody,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    user = await UserRepository(db).get_by_email(body.email)
    if user is None or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return await _issue(response, user, db, settings)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    plain = request.cookies.get(settings.auth_cookie_name)
    if not plain:
        raise HTTPException(status_code=401, detail="no refresh token")
    repo = RefreshTokenRepository(db)
    row = await repo.get_by_hash(security.hash_refresh(plain))
    if row is None or row.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="invalid refresh token")
    # 原子轮换:并发/重放下只有一个请求能赢得吊销;已吊销 或 抢不到吊销(竞态败者)=
    # 同一 refresh 被重用 → 吊销该用户全部 refresh(强制重新登录),堵住"双花"(I-1)。
    if row.revoked_at is not None or not await repo.revoke(row.id):
        await repo.revoke_all_for_user(row.user_id)
        await db.commit()
        raise HTTPException(status_code=401, detail="refresh token reuse detected")
    user = await UserRepository(db).get(row.user_id)
    if user is None:
        await db.commit()
        raise HTTPException(status_code=401, detail="invalid refresh token")
    return await _issue(response, user, db, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    plain = request.cookies.get(settings.auth_cookie_name)
    if plain:
        repo = RefreshTokenRepository(db)
        row = await repo.get_by_hash(security.hash_refresh(plain))
        if row is not None and row.revoked_at is None:
            await repo.revoke(row.id)
            await db.commit()
    response.delete_cookie(settings.auth_cookie_name, path="/")


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)):
    return user
