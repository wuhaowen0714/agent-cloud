# Plan A:鉴权核心 + 租户隔离(后端)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。步骤用 checkbox。

**Goal:** 后端真实身份 + 租户隔离:邮箱密码注册/登录、JWT access + httpOnly cookie refresh(轮换+重用检测)、`get_current_user`、所有端点改从 token 取 user 并按 owner 隔离(越权 404)、移除 `POST /users`。

**Architecture:** 新 `auth/security.py`(纯密码/JWT/refresh 工具)+ `api/auth.py`(端点)+ `api/deps.py` 加 `get_current_user` + `repositories/refresh_token.py`;逐端点 owner 化。Spec:[2026-06-08-auth-multitenancy-design.md](../specs/2026-06-08-auth-multitenancy-design.md)。

测试:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest ...`。

## 文件结构
- 新:`auth/__init__.py`、`auth/security.py`(纯函数)、`api/auth.py`、`repositories/refresh_token.py`、`models/refresh_token.py`、`schemas/auth.py`、`tests/test_auth.py`、`tests/test_authz.py`、迁移文件。
- 改:`config.py`、`models/user.py`、`api/deps.py`、所有收 user_id/owner_id 的端点 + 其 schema、`main.py`(注册 auth 路由、去 users 路由)、`conftest.py`(authed 夹具)、几乎所有 `tests/test_*` 的建会话辅助。

---

## Task 1:依赖 + 配置

- [ ] **Step 1:加依赖**:`cd services/backend && uv add pyjwt argon2-cffi`(cryptography 留 Plan C)。
- [ ] **Step 2:config.py** 加(在 compaction 段后):
```python
    # 鉴权(spec: auth-multitenancy)
    auth_secret: str = "dev-insecure-change-me"  # HS256 签名密钥;prod 必须经 env 覆盖
    access_token_ttl_seconds: int = 900  # 15min
    refresh_token_ttl_seconds: int = 2592000  # 30d
    auth_cookie_name: str = "ac_refresh"
    auth_cookie_secure: bool = False  # 本地 http=false;prod=true
```
- [ ] **Step 3** 跑现有 config 测试确认无碍 + 提交:
```bash
TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_config.py -q
git add services/backend/pyproject.toml services/backend/uv.lock services/backend/src/agent_cloud_backend/config.py
git commit -m "feat(backend): auth deps (pyjwt, argon2-cffi) + config knobs"
```

---

## Task 2:模型 + 迁移

- [ ] **Step 1:users.password_hash** —— `models/user.py` 加(迁移安全:server_default=""):
```python
    password_hash: Mapped[str] = mapped_column(nullable=False, server_default="")
```
- [ ] **Step 2:refresh_token 模型** —— 新 `models/refresh_token.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```
在 `models/__init__.py` 导入它(让 alembic/metadata 发现)。
- [ ] **Step 3:迁移** —— `alembic/versions/<id>_auth.py`(down_revision = 当前 head,用 `uv run alembic heads` 查):
```python
def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=False, server_default=""))
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])
    op.create_index(op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"])

def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_column("users", "password_hash")
```
- [ ] **Step 4** 应用 + 跑模型测试 + 提交:
```bash
AGENT_CLOUD_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud uv run alembic upgrade head
TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/ -q -k "model or session or user"
git add ... && git commit -m "feat(backend): users.password_hash + refresh_tokens (+migration)"
```

---

## Task 3:纯安全工具 `auth/security.py`(TDD)

- [ ] **Step 1:失败测试** `tests/test_security.py`:
```python
from agent_cloud_backend.auth import security

def test_password_hash_roundtrip():
    h = security.hash_password("hunter2")
    assert h != "hunter2"
    assert security.verify_password("hunter2", h) is True
    assert security.verify_password("wrong", h) is False

def test_access_token_roundtrip():
    import uuid
    uid = uuid.uuid4()
    tok = security.create_access_token(str(uid), secret="s", ttl_seconds=60)
    assert security.decode_access_token(tok, secret="s") == str(uid)

def test_access_token_expired_returns_none():
    tok = security.create_access_token("u", secret="s", ttl_seconds=-1)
    assert security.decode_access_token(tok, secret="s") is None

def test_access_token_bad_signature_returns_none():
    tok = security.create_access_token("u", secret="s", ttl_seconds=60)
    assert security.decode_access_token(tok, secret="other") is None

def test_refresh_token_gen_and_hash():
    plain, h = security.new_refresh_token()
    assert plain and h and h != plain
    assert security.hash_refresh(plain) == h
```
- [ ] **Step 2:实现** `auth/security.py`:
```python
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_ph = PasswordHasher()


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: str, *, secret: str, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(seconds=ttl_seconds)}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str) -> str | None:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return payload.get("sub")


def new_refresh_token() -> tuple[str, str]:
    plain = secrets.token_urlsafe(32)
    return plain, hash_refresh(plain)


def hash_refresh(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()
```
(注意:`verify_password` 的异常 import 名以实际 argon2 版本为准,执行时核对。)
- [ ] **Step 3** 跑过 + 提交。

---

## Task 4:refresh token 仓库

- [ ] **Step 1** `repositories/refresh_token.py`:
```python
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from agent_cloud_backend.models.refresh_token import RefreshToken
from agent_cloud_backend.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def create(self, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> RefreshToken:
        row = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_valid(self, token_hash: str) -> RefreshToken | None:
        res = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return res.scalar_one_or_none()

    async def revoke(self, token_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken).where(RefreshToken.id == token_id).values(revoked_at=datetime.now(UTC))
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
```
- [ ] **Step 2** 提交(测试随 auth 端点一起覆盖)。

---

## Task 5:auth 端点 + cookie

- [ ] **Step 1:schema** `schemas/auth.py`:`RegisterBody{email:EmailStr,password:str}`、`LoginBody{email:EmailStr,password:str}`、`TokenResponse{access_token:str, user:UserRead}`、`UserRead`(复用现有)。密码加 `min_length=8`。
- [ ] **Step 2:auth.py 端点**(prefix `/auth`):register / login / refresh / logout / me。要点:
  - register:邮箱占用 → 409;`hash_password`;建 user;签发(见下 `_issue`)。
  - login:`get_by_email` + `verify_password`,失败 → 401("invalid credentials",不区分邮箱/密码)。
  - `_issue(resp, user, db)`:`new_refresh_token()` → 存(过期=now+refresh_ttl)→ `resp.set_cookie(name, plain, httponly=True, secure=cfg, samesite="lax", path="/auth", max_age=refresh_ttl)` → 返回 `TokenResponse(access_token=create_access_token(...), user=...)`。
  - refresh:读 `request.cookies[name]` → `hash_refresh` → `get_valid`:不存在/过期 → 401;**已 revoked → revoke_all_for_user + 401(重用检测)**;否则 revoke 旧、建新、重设 cookie、发新 access。
  - logout:读 cookie → 有则 revoke;`resp.delete_cookie(name, path="/auth")`;204。
  - me:`Depends(get_current_user)` → UserRead。
- [ ] **Step 3:main.py** 注册 auth 路由;**移除 users 路由**(`POST /users`/`GET /users/{id}` 删除,users.py 可删或留空)。
- [ ] **Step 4:测试** `tests/test_auth.py`(用 `client`,无需 authed 夹具):注册→200+cookie;重复邮箱→409;登录对/错密码;refresh(带上一步 cookie)轮换;**用旧 cookie 再 refresh→401 且该用户全 token 失效**;logout 后 refresh→401;me 带 access→200、无 token→401。用 `client.cookies` 跨请求传 cookie。
- [ ] **Step 5** 全 auth 测试过 + ruff + 提交。

---

## Task 6:`get_current_user` 依赖

- [ ] **Step 1** `api/deps.py` 加:
```python
async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    uid = decode_access_token(token, secret=settings.auth_secret) if token else None
    if uid is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = await UserRepository(session).get(uuid.UUID(uid))
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user
```
(uuid 解析失败也 → 401:包 try/except ValueError。)
- [ ] **Step 2** 随 Task 5/7 测试覆盖(me 端点 + authz 测试)。

---

## Task 7:owner 化所有端点 + 迁移测试

**模式**(对每个端点):删掉客户端传入的 `user_id`/`owner_id`(query/body/form),改注入 `user = Depends(get_current_user)`,用 `user.id`;按 id 访问资源时校验归属,不符 → `HTTPException(404)`。

- [ ] **Step 1:逐端点改造(清单,逐个做并就近加/改测试)**:
  - `sessions.py`:`create_session`(body 去 user_id,用 user.id)、`list_sessions`(去 user_id query)。`SessionCreate` schema 去 `user_id`。**按 id 取 session 的地方**(turn、messages)校验 `s.user_id==user.id` 否则 404。
  - `agent_configs.py`:create(body 去 user_id)、list(去 query);get/update by id 校验归属。`AgentConfigCreate` 去 user_id。
  - `context_documents.py`:upsert(body 去 owner_id;scope=="user"→owner=user.id;scope=="agent"→校验该 agent 属本人)、list(去 owner_id;同上推导)。
  - `memory_entries.py`:append/list 同 context_documents(按 scope 推导 owner、agent 归属校验)。
  - `skills.py`:list(去 user_id)、create/upload(去 user_id,用 user.id)。
  - `agent_skills.py`:已用 agent.user_id —— 加 `get_current_user` 并校验 agent 属本人。
  - `files.py`:所有端点去 user_id(query/body),用 `str(user.id)`。`MkdirBody`/`MoveBody` 去 user_id。
  - `turn.py`:两个端点加 `get_current_user`;取 session 后校验 `s.user_id==user.id` 否则 404(取代隐式信任)。
  - `messages.py`:列消息校验 session 属本人。
  - 删 `users.py` 路由(已在 Task 5)。
- [ ] **Step 2:conftest authed 夹具** —— `conftest.py` 加:
```python
@pytest_asyncio.fixture
async def auth_client(client) -> AsyncClient:
    r = await client.post("/auth/register", json={"email": f"{uuid4()}@e.com", "password": "password123"})
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return client
```
(同理 `client_noraise` 版本若被用到。)需要"取当前用户 id"的测试可加一个返回 `(client, user_id)` 的 helper,从 register 响应的 `user.id` 拿。
- [ ] **Step 3:迁移现有测试** —— 把各 `tests/test_*.py` 里 `_make_session(client)` 之类(原先 `POST /users`+传 user_id)改用 `auth_client`:不再传 user_id;创建 session/agent 不带 user_id;断言用 register 返回的 user。**逐文件跑、逐个修**(test_*_e2e、test_turn_endpoint、test_turn_stream_endpoint、test_files_api、test_skill*、test_agent_config*、test_memory*、test_context* 等)。
- [ ] **Step 4:授权隔离测试** `tests/test_authz.py`:
  - 无 token → 受保护端点 401。
  - 用户 A 建 session,用户 B 的 token 访问该 session/turn/messages/files → 404。
  - 跨用户 agent_config/memory/skill 同理 404。
- [ ] **Step 5:全后端回归 + ruff + 提交**:
```bash
TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q && uv run ruff check src/ tests/
git add services/backend/ && git commit -m "feat(backend): tenant isolation — derive user from token, owner-scope all endpoints, drop POST /users"
```

---

## Task 8:.env.example + 收尾

- [ ] `.env.example` 加 `AGENT_CLOUD_AUTH_SECRET`、`AGENT_CLOUD_AUTH_COOKIE_SECURE` 注释(prod 必设)。
- [ ] worker 套件保持绿(本 plan 不动 worker)。
- [ ] 提交。

---

## Self-Review
- Spec §3/§4 覆盖:注册/登录/refresh 轮换+重用检测/logout/me ✓;get_current_user + 全端点 owner 化 + 404 ✓;移除 POST /users ✓;cookie refresh + 内存 access ✓。
- 破坏性:所有 user_id 入参移除 → 测试全迁移(Task 7 Step 3)是大头,逐文件跑。
- 边界:uuid 解析失败→401;邮箱占用→409;登录失败不区分→401;refresh 重用→吊销全部。
- 默认值与 spec 一致(argon2id、access 15min、refresh 30d cookie、越权 404)。
- 后续:Plan B(前端外壳/侧栏)、Plan C(BYO-Key)。
