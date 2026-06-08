# Plan C:BYO-Key(自带 LLM 凭据)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。本环境约定:机械实现由 controller 直接做(子 agent 大批量写入会截断),子 agent 留给审查。每个任务跑完整回归。Spec:[2026-06-08-auth-multitenancy-design.md](../specs/2026-06-08-auth-multitenancy-design.md) §2/§5/§8/§10。依赖:Plan A(鉴权+隔离)、Plan B(前端外壳)已落地。

**Goal:** 每用户可自带 LLM 凭据(provider key + base_url),加密存储;回合按 agent 选用本人凭据,无则回退全局 key;凭据永不回前端明文、永不进 sandbox。

**Architecture:** 凭据用后端主密钥(env)AES-GCM 加密落 `provider_credentials` 表。回合组装时后端按 `agent.key_ref` 取本人凭据→解密→把 `api_key`/`base_url` 放进 RunTurn/Summarize 的 `Agent` proto(新增 2 字段,仅 BE→Worker)。worker factory 优先用请求里的 key/base_url,否则用全局 settings。前端在设置抽屉加 "Provider Keys" 管理区 + agent 设置选凭据下拉。

**Tech Stack:** FastAPI + SQLAlchemy(async)+ alembic;`cryptography`(AES-GCM,已在 venv);gRPC/protobuf;React19 + Vite + TS + Tailwind;后端测试 `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest`,前端 `npx vitest run` + `npm run lint`(tsc)。

---

## 现状(已存在,无需新建)
- proto `Agent` 已有 `key_ref = 5`;需加 `api_key = 6; base_url = 7`。
- `agent_configs.key_ref`(model + schema)已存在,**无需迁移**。
- worker `factory(model, provider, key_ref)` 已存在但忽略 key_ref;`ProviderFactory = Callable[[str,str,str], Provider]`;server.py 3 处调用传 `request.agent.key_ref`。
- `cryptography 45.0.5` 已在 venv(仍需写进 backend pyproject 显式依赖)。
- alembic head = `d2e3f4a5b6c7`(新迁移 down_revision 用它)。
- proto 重新生成:仓库根 `bash scripts/gen_protos.sh`(生成进 `packages/common/src/agent_cloud/v1/`)。
- `assemble.py`(RunTurn)与 `compaction.py`(SummarizeRequest)都构造 `worker_pb2.Agent` —— 两处都要填 key。

## 文件结构
- 新:`backend/.../crypto.py`(AES-GCM + mask)、`models/provider_credential.py`、`repositories/provider_credential.py`、`schemas/credential.py`、`api/credentials.py`、`turn/credentials.py`(key 解析)、alembic 迁移、`frontend/src/components/settings/KeysPanel.tsx`、`frontend/src/components/settings/KeysPanel.test.tsx`。
- 改:`config.py`(+credential_key)、`backend/pyproject.toml`(+cryptography)、`api/ownership.py`(+owned_credential)、`main.py`(注册 router)、`protos/.../worker.proto`、worker `factory.py`/`server.py`/`config.py`(用 per-request key)、`turn/assemble.py`+`turn/compaction.py`(填 key)、`.env.example`、前端 `types.ts`/`api/client.ts`/`store.ts`/`settings/SettingsDrawer.tsx`/`settings/AgentSettings.tsx`/`components/AccountMenu.tsx`。

---

## Task 1:crypto.py(AES-GCM 加解密 + 掩码)+ config + 依赖

**Files:**
- Create: `services/backend/src/agent_cloud_backend/crypto.py`
- Modify: `services/backend/src/agent_cloud_backend/config.py`、`services/backend/pyproject.toml`
- Test: `services/backend/tests/test_crypto.py`

- [ ] **Step 1: 加依赖 + config 项**

`config.py` 在 `auth_cookie_secure` 行后加:
```python
    # BYO-Key:凭据 AES-GCM 主密钥(base64 编码的 32 字节);空 = 凭据功能不可用。
    # 生成:python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
    credential_key: str = ""
```
`backend/pyproject.toml` 的 dependencies 末尾(`argon2-cffi` 后)加一行:
```
    "cryptography>=43",
```

- [ ] **Step 2: 写失败测试** `services/backend/tests/test_crypto.py`

```python
import base64

import pytest

from agent_cloud_backend.crypto import decrypt, encrypt, load_credential_key, mask

KEY = base64.b64encode(b"\x01" * 32).decode()


def test_encrypt_decrypt_roundtrip():
    k = load_credential_key(KEY)
    blob = encrypt("sk-secret-123", k)
    assert isinstance(blob, bytes) and blob != b"sk-secret-123"
    assert decrypt(blob, k) == "sk-secret-123"


def test_each_encrypt_uses_fresh_nonce():
    k = load_credential_key(KEY)
    assert encrypt("same", k) != encrypt("same", k)  # 随机 nonce → 密文不同


def test_decrypt_with_wrong_key_fails():
    k = load_credential_key(KEY)
    other = load_credential_key(base64.b64encode(b"\x02" * 32).decode())
    blob = encrypt("x", k)
    with pytest.raises(Exception):
        decrypt(blob, other)


def test_load_key_rejects_bad_length():
    with pytest.raises(ValueError):
        load_credential_key(base64.b64encode(b"short").decode())
    with pytest.raises(ValueError):
        load_credential_key("")


def test_mask_keeps_only_prefix_and_suffix():
    assert mask("sk-abcdefgh1234") == "sk-…1234"
    assert mask("short") == "…"  # 太短不暴露
```

- [ ] **Step 3: 跑测试确认失败** `cd services/backend && uv run pytest tests/test_crypto.py -q`(Expected: ImportError / module not found)

- [ ] **Step 4: 实现** `services/backend/src/agent_cloud_backend/crypto.py`

```python
"""凭据加密:AES-256-GCM(随机 96-bit nonce,nonce 前置于密文)。主密钥来自 env
(base64 的 32 字节),接口 KMS-ready(后续把 encrypt/decrypt 换成 KMS 调用即可)。"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12


def load_credential_key(b64: str) -> bytes:
    """解码 env 里的 base64 主密钥,校验为 32 字节(AES-256)。"""
    if not b64:
        raise ValueError("credential key not configured (set AGENT_CLOUD_CREDENTIAL_KEY)")
    raw = base64.b64decode(b64)
    if len(raw) != 32:
        raise ValueError(f"credential key must be 32 bytes (got {len(raw)})")
    return raw


def encrypt(plain: str, key: bytes) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(key).encrypt(nonce, plain.encode(), None)
    return nonce + ct


def decrypt(blob: bytes, key: bytes) -> str:
    nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def mask(plain: str) -> str:
    """展示用掩码:前 3 + … + 后 4;太短(≤8)只显 …,绝不暴露明文。"""
    return f"{plain[:3]}…{plain[-4:]}" if len(plain) > 8 else "…"
```

- [ ] **Step 5: 跑测试确认通过** `cd services/backend && uv run pytest tests/test_crypto.py -q`(Expected: 5 passed)

- [ ] **Step 6: 提交**
```bash
git add services/backend/src/agent_cloud_backend/crypto.py services/backend/tests/test_crypto.py services/backend/src/agent_cloud_backend/config.py services/backend/pyproject.toml
git commit -m "feat(backend): credential crypto (AES-GCM) + credential_key config"
```

---

## Task 2:provider_credentials 模型 + 仓库 + 迁移

**Files:**
- Create: `services/backend/src/agent_cloud_backend/models/provider_credential.py`、`services/backend/src/agent_cloud_backend/repositories/provider_credential.py`、`services/backend/alembic/versions/e3f4a5b6c7d8_provider_credentials.py`
- Modify: `services/backend/src/agent_cloud_backend/models/__init__.py`(若 __init__ 汇总 model 导入则加;否则跳过)
- Test: 仓库行为在 Task 3 的 API 测试里覆盖,此处不单测。

- [ ] **Step 1: 模型** `models/provider_credential.py`

```python
import uuid

from sqlalchemy import ForeignKey, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from agent_cloud_backend.models.base import Base, TimestampMixin, uuid_pk


class ProviderCredential(Base, TimestampMixin):
    __tablename__ = "provider_credentials"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(nullable=False)
    base_url: Mapped[str] = mapped_column(nullable=False, default="")
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    masked: Mapped[str] = mapped_column(nullable=False, default="")  # 展示掩码,免解密即可列出
```

> 注:`TimestampMixin` 提供 `created_at`(见 `models/base.py`,与 refresh_token 一致)。不需 updated_at(凭据不可改,只增删)。

- [ ] **Step 2: 仓库** `repositories/provider_credential.py`

```python
import uuid

from sqlalchemy import select

from agent_cloud_backend.models.provider_credential import ProviderCredential
from agent_cloud_backend.repositories.base import BaseRepository


class ProviderCredentialRepository(BaseRepository[ProviderCredential]):
    model = ProviderCredential

    async def create(
        self, user_id: uuid.UUID, name: str, base_url: str, api_key_encrypted: bytes, masked: str
    ) -> ProviderCredential:
        row = ProviderCredential(
            user_id=user_id,
            name=name,
            base_url=base_url,
            api_key_encrypted=api_key_encrypted,
            masked=masked,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_user(self, user_id: uuid.UUID) -> list[ProviderCredential]:
        res = await self.session.execute(
            select(ProviderCredential)
            .where(ProviderCredential.user_id == user_id)
            .order_by(ProviderCredential.created_at)
        )
        return list(res.scalars().all())
```

> 删除直接用 `db.delete(row)`(在 API 里,行已由 owned_credential 取回);取单行用 `db.get(ProviderCredential, id)`,故仓库不再加 get/delete。

- [ ] **Step 3: 生成迁移**

`cd services/backend && uv run alembic revision -m "provider_credentials"` 生成空迁移,**改文件名/内容**为(确保 `down_revision = "d2e3f4a5b6c7"`):
```python
"""provider_credentials

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""
import sqlalchemy as sa
from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False, server_default=""),
        sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("masked", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_provider_credentials_user_id", "provider_credentials", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_provider_credentials_user_id", table_name="provider_credentials")
    op.drop_table("provider_credentials")
```

> 用 `uuid_pk()`/`TimestampMixin` 的真实列类型对齐既有迁移(参考 `d2e3f4a5b6c7_auth.py` 里 refresh_tokens 的列写法;若那里用的是 `sa.Uuid` 之外的类型,照抄之)。

- [ ] **Step 4: 应用迁移到 dev 库** `cd services/backend && AGENT_CLOUD_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud" uv run alembic upgrade head`(Expected: 无报错,head→e3f4a5b6c7d8)

- [ ] **Step 5: 提交**
```bash
git add services/backend/src/agent_cloud_backend/models/provider_credential.py services/backend/src/agent_cloud_backend/repositories/provider_credential.py services/backend/alembic/versions/e3f4a5b6c7d8_provider_credentials.py
git commit -m "feat(backend): provider_credentials model + repo + migration"
```

---

## Task 3:凭据 API(CRUD,掩码,owner 隔离)

**Files:**
- Create: `services/backend/src/agent_cloud_backend/schemas/credential.py`、`services/backend/src/agent_cloud_backend/api/credentials.py`
- Modify: `services/backend/src/agent_cloud_backend/api/ownership.py`、`services/backend/src/agent_cloud_backend/main.py`
- Test: `services/backend/tests/test_credentials_api.py`

- [ ] **Step 1: schemas** `schemas/credential.py`

```python
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CredentialCreate(BaseModel):
    name: str
    base_url: str = ""
    api_key: str  # 明文,仅入站;绝不回显


class CredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    base_url: str
    masked: str
    created_at: datetime
```

- [ ] **Step 2: ownership 加 owned_credential** —— `api/ownership.py` 末尾追加(并在文件顶部 import `ProviderCredential`):

顶部 import 区加:
```python
from agent_cloud_backend.models.provider_credential import ProviderCredential
```
文件末尾加:
```python
async def owned_credential(
    cred_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> ProviderCredential:
    c = await db.get(ProviderCredential, cred_id)
    if c is None or c.user_id != user_id:
        raise HTTPException(status_code=404, detail="credential not found")
    return c
```

- [ ] **Step 3: 写失败测试** `services/backend/tests/test_credentials_api.py`

```python
import uuid


async def _auth_headers(client):
    r = await client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_create_returns_masked_never_plaintext(client):
    h = await _auth_headers(client)
    r = await client.post(
        "/credentials",
        json={"name": "openrouter", "base_url": "https://or/v1", "api_key": "sk-abcdef123456"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["masked"] == "sk-…3456"
    assert "api_key" not in body and "sk-abcdef123456" not in r.text


async def test_list_only_own_masked(client):
    h = await _auth_headers(client)
    await client.post(
        "/credentials", json={"name": "a", "base_url": "", "api_key": "sk-zzzz1111"}, headers=h
    )
    r = await client.get("/credentials", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["masked"] == "sk-…1111"


async def test_requires_auth(client):
    assert (await client.get("/credentials")).status_code == 401


async def test_cross_user_delete_404(client):
    h1 = await _auth_headers(client)
    cid = (
        await client.post(
            "/credentials", json={"name": "a", "base_url": "", "api_key": "sk-aaaa2222"}, headers=h1
        )
    ).json()["id"]
    h2 = await _auth_headers(client)
    assert (await client.delete(f"/credentials/{cid}", headers=h2)).status_code == 404
    # 本人删成功
    assert (await client.delete(f"/credentials/{cid}", headers=h1)).status_code == 204
```

> 测试需要 `AGENT_CLOUD_CREDENTIAL_KEY` 有值。在 `conftest.py` 的测试环境设置处(settings override / monkeypatch env)注入一个固定 base64 key;若 conftest 用 `get_settings` 依赖覆盖,则在该 fixture 里设 `credential_key=base64.b64encode(b"\x07"*32).decode()`。**Step 实现时先看 conftest 怎么注入 settings,照同样方式补 credential_key。**

- [ ] **Step 4: 跑测试确认失败** `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_credentials_api.py -q`(Expected: 404/无路由 → 失败)

- [ ] **Step 5: 实现 API** `api/credentials.py`

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend import crypto
from agent_cloud_backend.api.deps import get_current_user, get_session
from agent_cloud_backend.api.ownership import owned_credential
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.models.user import User
from agent_cloud_backend.repositories.provider_credential import ProviderCredentialRepository
from agent_cloud_backend.schemas.credential import CredentialCreate, CredentialRead

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.post("", response_model=CredentialRead, status_code=status.HTTP_201_CREATED)
async def create_credential(
    body: CredentialCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    key = crypto.load_credential_key(settings.credential_key)
    row = await ProviderCredentialRepository(db).create(
        user_id=user.id,
        name=body.name,
        base_url=body.base_url,
        api_key_encrypted=crypto.encrypt(body.api_key, key),
        masked=crypto.mask(body.api_key),
    )
    await db.commit()
    return row


@router.get("", response_model=list[CredentialRead])
async def list_credentials(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await ProviderCredentialRepository(db).list_for_user(user.id)


@router.delete("/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    cred_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    row = await owned_credential(cred_id, user.id, db)
    await db.delete(row)
    await db.commit()
```

- [ ] **Step 6: 注册 router** —— `main.py` 的 import 块加 `credentials`,`include_router` 的 tuple 里加 `credentials,`:
```python
from agent_cloud_backend.api import (
    agent_configs,
    agent_skills,
    auth,
    context_documents,
    credentials,
    files,
    memory_entries,
    messages,
    sessions,
    skills,
    turn,
)
```
并在 `for module in (auth, ... , files):` 里加入 `credentials`。

- [ ] **Step 7: 跑测试确认通过** `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_credentials_api.py -q`(Expected: 4 passed)

- [ ] **Step 8: 提交**
```bash
git add services/backend/src/agent_cloud_backend/schemas/credential.py services/backend/src/agent_cloud_backend/api/credentials.py services/backend/src/agent_cloud_backend/api/ownership.py services/backend/src/agent_cloud_backend/main.py services/backend/tests/test_credentials_api.py
git commit -m "feat(backend): credentials CRUD API (masked, owner-scoped)"
```

---

## Task 4:proto 加 api_key/base_url + worker factory 用 per-request key

**Files:**
- Modify: `protos/agent_cloud/v1/worker.proto`、`packages/common/src/agent_cloud/v1/worker_pb2.py`(生成物)、`services/worker/src/agent_cloud_worker/factory.py`、`services/worker/src/agent_cloud_worker/server.py`
- Test: `services/worker/tests/test_factory.py`

- [ ] **Step 1: 改 proto** —— `worker.proto` 的 `message Agent` 加两字段:
```proto
message Agent {
  string model = 1;
  string provider = 2;
  string thinking_level = 3;
  repeated string enabled_tools = 4;
  string key_ref = 5;
  string api_key = 6;   // 后端按 key_ref 解密填入;worker 用之造 client。仅 BE→Worker,绝不进 sandbox。
  string base_url = 7;
}
```

- [ ] **Step 2: 重新生成 pb2** —— 仓库根 `bash scripts/gen_protos.sh`(Expected: "generated stubs under packages/common/src/agent_cloud/v1/")

- [ ] **Step 3: 写失败测试** `services/worker/tests/test_factory.py`(若已存在则追加这两个用例)

```python
from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.factory import _effective_credentials


def test_per_request_key_overrides_global():
    s = WorkerSettings(openai_api_key="GLOBAL", openai_base_url="https://global/v1")
    key, base = _effective_credentials(s, "sk-user", "https://user/v1")
    assert key == "sk-user" and base == "https://user/v1"


def test_per_request_key_without_base_url_falls_back_to_global_base():
    s = WorkerSettings(openai_api_key="GLOBAL", openai_base_url="https://global/v1")
    key, base = _effective_credentials(s, "sk-user", "")
    assert key == "sk-user" and base == "https://global/v1"


def test_no_request_key_uses_global():
    s = WorkerSettings(openai_api_key="GLOBAL", openai_base_url="https://global/v1")
    key, base = _effective_credentials(s, "", "")
    assert key == "GLOBAL" and base == "https://global/v1"
```

- [ ] **Step 4: 跑测试确认失败** `cd services/worker && uv run pytest tests/test_factory.py -q`(Expected: ImportError `_effective_credentials`)

- [ ] **Step 5: 改 factory** `factory.py` 全文:

```python
from __future__ import annotations

from openai import AsyncOpenAI

from agent_cloud_worker.config import WorkerSettings
from agent_cloud_worker.openai_provider import OpenAIProvider
from agent_cloud_worker.provider import Provider
from agent_cloud_worker.server import ProviderFactory


def _effective_credentials(settings: WorkerSettings, api_key: str, base_url: str) -> tuple[str, str]:
    """BYO-Key:请求带 api_key 则用之(base_url 缺省回退全局);否则用全局 settings。"""
    if api_key:
        return api_key, base_url or settings.openai_base_url
    return settings.openai_api_key, settings.openai_base_url


def build_provider_factory(settings: WorkerSettings) -> ProviderFactory:
    """造 provider_factory(model, provider, api_key, base_url)->Provider。
    openai SDK 自带 timeout + max_retries(自动退避 429/5xx)。"""

    def factory(model: str, provider: str, api_key: str, base_url: str) -> Provider:
        eff_key, eff_base = _effective_credentials(settings, api_key, base_url)
        if not eff_key:
            raise RuntimeError(
                "no API key (set AGENT_CLOUD_WORKER_OPENAI_API_KEY or attach a credential)"
            )
        client = AsyncOpenAI(
            api_key=eff_key,
            base_url=eff_base,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
        return OpenAIProvider(
            client=client,
            model=model,
            max_tokens=settings.request_max_tokens,
            max_tokens_param=settings.max_tokens_param,
        )

    return factory
```

- [ ] **Step 6: 改 server.py** —— `ProviderFactory` 类型 + 3 处调用。

类型(第 28 行附近):
```python
# 由 agent 的 (model, provider, api_key, base_url) 造一个 Provider。
ProviderFactory = Callable[[str, str, str, str], Provider]
```
3 处 `self._provider_factory(request.agent.model, request.agent.provider, request.agent.key_ref)` 全部改为:
```python
            provider = self._provider_factory(
                request.agent.model,
                request.agent.provider,
                request.agent.api_key,
                request.agent.base_url,
            )
```
(RunTurn ~66、RunTurnStream ~122、Summarize ~183 三处。)

- [ ] **Step 7: 跑测试确认通过** `cd services/worker && uv run pytest tests/test_factory.py -q`(Expected: 3 passed)

- [ ] **Step 8: 提交**
```bash
git add protos/agent_cloud/v1/worker.proto packages/common/src/agent_cloud/v1/ services/worker/src/agent_cloud_worker/factory.py services/worker/src/agent_cloud_worker/server.py services/worker/tests/test_factory.py
git commit -m "feat(worker): per-request api_key/base_url (proto + factory)"
```

---

## Task 5:后端按 key_ref 解密并填进 Agent proto

**Files:**
- Create: `services/backend/src/agent_cloud_backend/turn/credentials.py`
- Modify: `services/backend/src/agent_cloud_backend/turn/assemble.py`、`services/backend/src/agent_cloud_backend/turn/compaction.py`
- Test: `services/backend/tests/test_turn_credentials.py`

- [ ] **Step 1: 写失败测试** `services/backend/tests/test_turn_credentials.py`

```python
import base64
import uuid

import pytest

from agent_cloud_backend import crypto
from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.provider_credential import ProviderCredential
from agent_cloud_backend.turn.credentials import resolve_agent_key

_KEY_B64 = base64.b64encode(b"\x07" * 32).decode()


async def _mk_cred(db, user_id, plain="sk-real-key", base="https://x/v1"):
    key = crypto.load_credential_key(_KEY_B64)
    row = ProviderCredential(
        user_id=user_id, name="c", base_url=base,
        api_key_encrypted=crypto.encrypt(plain, key), masked=crypto.mask(plain),
    )
    db.add(row)
    await db.flush()
    return row


async def test_resolves_own_credential(db_session):
    settings = Settings(credential_key=_KEY_B64)
    uid = uuid.uuid4()
    cred = await _mk_cred(db_session, uid)
    api_key, base_url = await resolve_agent_key(db_session, str(cred.id), uid, settings)
    assert api_key == "sk-real-key" and base_url == "https://x/v1"


async def test_empty_key_ref_returns_blank(db_session):
    settings = Settings(credential_key=_KEY_B64)
    assert await resolve_agent_key(db_session, "", uuid.uuid4(), settings) == ("", "")


async def test_foreign_credential_falls_back_to_blank(db_session):
    settings = Settings(credential_key=_KEY_B64)
    cred = await _mk_cred(db_session, uuid.uuid4())  # 属于另一个 user
    api_key, base_url = await resolve_agent_key(db_session, str(cred.id), uuid.uuid4(), settings)
    assert (api_key, base_url) == ("", "")  # 不属本人 → 回退全局
```

> `db_session` fixture:看 conftest.py 现有的 async db fixture 名(可能叫 `db_session`/`db`/`session`)。**实现时对齐既有名字**;若需要先建 user 满足 FK,则照 conftest 建一个真实 user 并用其 id(本测试用裸 uuid + flush;若 FK 约束报错,改成先建 user)。

- [ ] **Step 2: 跑测试确认失败** `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_turn_credentials.py -q`(Expected: ImportError)

- [ ] **Step 3: 实现解析器** `turn/credentials.py`

```python
"""回合用凭据解析:按 agent.key_ref 取本人凭据→解密→(api_key, base_url)。
找不到/不属本人/key_ref 非法 → ("",""),让 worker 回退全局 key(spec §5)。"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from agent_cloud_backend import crypto
from agent_cloud_backend.config import Settings
from agent_cloud_backend.models.provider_credential import ProviderCredential


async def resolve_agent_key(
    db: AsyncSession, key_ref: str, user_id: uuid.UUID, settings: Settings
) -> tuple[str, str]:
    if not key_ref:
        return "", ""
    try:
        cid = uuid.UUID(key_ref)
    except ValueError:
        return "", ""
    cred = await db.get(ProviderCredential, cid)
    if cred is None or cred.user_id != user_id:
        return "", ""  # 不属本人或不存在 → 回退全局,不泄漏、不报错
    key = crypto.load_credential_key(settings.credential_key)
    return crypto.decrypt(cred.api_key_encrypted, key), cred.base_url
```

- [ ] **Step 4: assemble.py 填 key** —— 顶部 import 加:
```python
from agent_cloud_backend.config import get_settings
from agent_cloud_backend.turn.credentials import resolve_agent_key
```
在构造 `worker_pb2.Agent(...)` 之前解析,并把结果放进 proto。把 `return worker_pb2.RunTurnRequest(...)` 里的 `agent=worker_pb2.Agent(...)` 改为先算 key:
```python
    api_key, base_url = await resolve_agent_key(db, agent.key_ref or "", session.user_id, get_settings())
    agent_proto = worker_pb2.Agent(
        model=agent.model,
        provider=agent.provider,
        thinking_level=agent.thinking_level or "",
        enabled_tools=list(agent.enabled_tools),
        key_ref=agent.key_ref or "",
        api_key=api_key,
        base_url=base_url,
    )
```
并把 `RunTurnRequest(... agent=worker_pb2.Agent(...) ...)` 改成 `agent=agent_proto`。

- [ ] **Step 5: compaction.py 填 key** —— 顶部 import 加 `from agent_cloud_backend.turn.credentials import resolve_agent_key`;`compact()` 已有 `settings`? 没有 —— 它接 `worker_endpoint`、`keep_recent`。给 `compact` 加一个 `settings: Settings` 形参,调用方(`maybe_compact_after_turn`/`force_compact`)已持有 `settings`,传进去。然后在构造 SummarizeRequest 前解析并填:
```python
    api_key, base_url = await resolve_agent_key(db, agent.key_ref or "", session.user_id, settings)
    req = worker_pb2.SummarizeRequest(
        agent=worker_pb2.Agent(
            model=agent.model, provider=agent.provider, key_ref=agent.key_ref or "",
            api_key=api_key, base_url=base_url,
        ),
        prior_summary=session.summary,
        messages=[msg_to_proto(orm_to_common(m)) for m in fold_msgs],
    )
```
`compact` 签名改 `async def compact(session_id, *, worker_endpoint, keep_recent, settings)`;`maybe_compact_after_turn` 调用加 `settings=settings`;`force_compact` 调用加 `settings=settings`(它已有 `settings` 形参)。导入 `Settings` 已在文件顶部(`from agent_cloud_backend.config import Settings`)。

- [ ] **Step 6: 跑相关测试** `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_turn_credentials.py tests/test_compaction*.py -q`(Expected: 全 passed;若 compaction 测试因 compact 新增必填 settings 形参而报错,改这些测试的 compact 调用传 `settings=Settings()`)

- [ ] **Step 7: 提交**
```bash
git add services/backend/src/agent_cloud_backend/turn/credentials.py services/backend/src/agent_cloud_backend/turn/assemble.py services/backend/src/agent_cloud_backend/turn/compaction.py services/backend/tests/test_turn_credentials.py
git commit -m "feat(backend): resolve agent key_ref -> decrypt -> Agent proto (run + summarize)"
```

---

## Task 6:前端 —— 凭据 API + Provider Keys UI + agent 选凭据 + 账户入口

**Files:**
- Create: `frontend/src/components/settings/KeysPanel.tsx`、`frontend/src/components/settings/KeysPanel.test.tsx`
- Modify: `frontend/src/types.ts`、`frontend/src/api/client.ts`、`frontend/src/store.ts`、`frontend/src/components/settings/SettingsDrawer.tsx`、`frontend/src/components/settings/AgentSettings.tsx`、`frontend/src/components/AccountMenu.tsx`

- [ ] **Step 1: 类型 + api** —— `types.ts` 末尾加:
```ts
export interface ProviderCredential { id: string; name: string; base_url: string; masked: string; created_at: string }
```
`api/client.ts` 在 skills 方法后加:
```ts
  // ── provider credentials(BYO-Key)──
  listCredentials: () => http<ProviderCredential[]>("/credentials"),
  createCredential: (body: { name: string; base_url: string; api_key: string }) =>
    http<ProviderCredential>("/credentials", { method: "POST", body: JSON.stringify(body) }),
  deleteCredential: (id: string) => http<void>(`/credentials/${id}`, { method: "DELETE" }),
```
并把 `ProviderCredential` 加进顶部 `import type { ... } from "../types"`。

- [ ] **Step 2: store 加 settingsTab** —— `store.ts`:`AppState` 加 `settingsTab: "agent" | "skills" | "keys"`;`openSettings` 签名改 `(tab?: "agent" | "skills" | "keys") => void`。初值 `settingsTab: "agent"`。实现:
```ts
  openSettings: (tab = "agent") => set({ settingsOpen: true, settingsTab: tab }),
```
(`AppState` 接口里 `openSettings: () => void` 改成 `openSettings: (tab?: "agent" | "skills" | "keys") => void`。)

- [ ] **Step 3: SettingsDrawer 用 store tab + 加 keys 标签** —— `SettingsDrawer.tsx`:删本地 `const [tab, setTab] = useState(...)`,改读 store:
```ts
  const tab = useStore((s) => s.settingsTab)
  const setTab = (t: "agent" | "skills" | "keys") => useStore.setState({ settingsTab: t })
```
标签栏加第三个按钮 + 内容分支:
```tsx
          <button className={tabCls("keys")} onClick={() => setTab("keys")}>
            Provider Keys
          </button>
```
内容区改:
```tsx
          {tab === "agent" && <AgentSettings />}
          {tab === "skills" && <SkillsPanel />}
          {tab === "keys" && <KeysPanel />}
```
顶部 import `KeysPanel`。

- [ ] **Step 4: KeysPanel 组件** `components/settings/KeysPanel.tsx`

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"

export function KeysPanel() {
  const userId = useStore((s) => s.userId)
  const qc = useQueryClient()
  const [form, setForm] = useState({ name: "", base_url: "", api_key: "" })

  const { data: creds = [] } = useQuery({
    queryKey: ["credentials", userId],
    queryFn: () => api.listCredentials(),
    enabled: !!userId,
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ["credentials", userId] })
  const create = useMutation({
    mutationFn: () => api.createCredential(form),
    onSuccess: () => {
      setForm({ name: "", base_url: "", api_key: "" })
      refresh()
    },
  })
  const remove = useMutation({ mutationFn: (id: string) => api.deleteCredential(id), onSuccess: refresh })

  const field = "w-full rounded border border-slate-300 px-2 py-1 text-sm"
  return (
    <div className="space-y-4 text-sm">
      <div className="space-y-1">
        <div className="font-medium text-slate-700">已保存的凭据</div>
        {creds.length === 0 && <div className="text-xs text-slate-400">还没有凭据,下面添加一个</div>}
        {creds.map((c) => (
          <div key={c.id} className="flex items-center gap-2 rounded border border-slate-200 px-2 py-1">
            <span className="min-w-0 flex-1 truncate">
              <span className="text-slate-700">{c.name}</span>
              <span className="ml-2 font-mono text-xs text-slate-400">{c.masked}</span>
              {c.base_url && <span className="ml-2 text-xs text-slate-400">{c.base_url}</span>}
            </span>
            <button
              className="shrink-0 text-xs text-slate-400 hover:text-red-600"
              onClick={() => remove.mutate(c.id)}
            >
              删除
            </button>
          </div>
        ))}
      </div>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (form.name && form.api_key) create.mutate()
        }}
      >
        <div className="font-medium text-slate-700">添加凭据</div>
        <input className={field} placeholder="名称(如 openrouter)" value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input className={field} placeholder="base_url(可选,留空用默认)" value={form.base_url}
          onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
        <input className={field} type="password" placeholder="API Key" value={form.api_key}
          onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
        <button
          className="rounded bg-brand-600 px-3 py-1 text-sm text-white hover:bg-brand-700 disabled:opacity-40"
          disabled={!form.name || !form.api_key || create.isPending}
        >
          {create.isPending ? "保存中…" : "保存"}
        </button>
      </form>
      <p className="text-xs text-slate-400">Key 加密存储,只显示掩码;在 Agent 设置里可指定用哪个凭据。</p>
    </div>
  )
}
```

- [ ] **Step 5: AgentSettings 加 key_ref 下拉** —— `AgentSettings.tsx` 的 `AgentEditor`:`form` state 加 `key_ref: ""`;首次灌草稿处加 `key_ref: agent.key_ref ?? ""`;保存 `patchAgent` 的 body 加 `key_ref: form.key_ref || null`(`patchAgent` 的 Pick 类型需含 `key_ref` —— client.ts 里 `patchAgent` 的 `Pick<AgentConfig, ...>` 加 `"key_ref"`)。拉凭据列表 + 渲染下拉(放在 provider 输入后):
```tsx
  const { data: creds = [] } = useQuery({ queryKey: ["credentials", userId], queryFn: () => api.listCredentials() })
```
```tsx
        <select className={field} value={form.key_ref} onChange={(e) => setForm({ ...form, key_ref: e.target.value })}>
          <option value="">凭据:全局共享 Key</option>
          {creds.map((c) => (
            <option key={c.id} value={c.id}>{c.name} · {c.masked}</option>
          ))}
        </select>
```
> `patchAgent` 类型:`client.ts` 把 `Pick<AgentConfig, "name" | "model" | "provider" | "thinking_level" | "enabled_tools">` 改为 `Pick<AgentConfig, "name" | "model" | "provider" | "thinking_level" | "enabled_tools" | "key_ref">`。`AgentConfig` 类型已含 `key_ref`?——`types.ts` 的 `AgentConfig` 当前**没有** key_ref,需补:在 `AgentConfig` 接口加 `key_ref: string | null`。

- [ ] **Step 6: AccountMenu 加 Provider Keys 入口** —— `AccountMenu.tsx`:菜单里"工作区文件"按钮后、"登出"前加:
```tsx
          <button
            className={item}
            onClick={() => {
              useStore.getState().openSettings("keys")
              setOpen(false)
            }}
          >
            <span className="w-3.5 shrink-0 text-center">🔑</span>
            <span>Provider Keys</span>
          </button>
```

- [ ] **Step 7: KeysPanel 测试** `components/settings/KeysPanel.test.tsx`

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { useStore } from "../../store"
import { KeysPanel } from "./KeysPanel"

vi.mock("../../api/client", () => ({
  api: {
    listCredentials: vi.fn().mockResolvedValue([
      { id: "c1", name: "openrouter", base_url: "https://or/v1", masked: "sk-…1234", created_at: "" },
    ]),
    createCredential: vi.fn().mockResolvedValue({ id: "c2", name: "x", base_url: "", masked: "sk-…9999", created_at: "" }),
    deleteCredential: vi.fn().mockResolvedValue(undefined),
  },
}))

const wrap = (ui: ReactNode) => <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>

describe("KeysPanel", () => {
  beforeEach(() => useStore.setState({ userId: "u1" }))

  it("lists existing credentials by mask (never plaintext)", async () => {
    render(wrap(<KeysPanel />))
    expect(await screen.findByText("sk-…1234")).toBeInTheDocument()
    expect(screen.getByText("openrouter")).toBeInTheDocument()
  })

  it("submits a new credential", async () => {
    const { api } = await import("../../api/client")
    render(wrap(<KeysPanel />))
    fireEvent.change(screen.getByPlaceholderText("名称(如 openrouter)"), { target: { value: "x" } })
    fireEvent.change(screen.getByPlaceholderText("API Key"), { target: { value: "sk-9999" } })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))
    await waitFor(() =>
      expect(api.createCredential).toHaveBeenCalledWith({ name: "x", base_url: "", api_key: "sk-9999" }),
    )
  })
})
```

- [ ] **Step 8: 回归** `cd frontend && npm run lint && npx vitest run`(Expected: tsc 干净;全绿)

- [ ] **Step 9: 提交**
```bash
git add frontend/src
git commit -m "feat(frontend): provider keys UI + agent credential selector + account entry"
```

---

## Task 7:.env.example + 全栈回归 + 提交

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: .env.example** —— 在鉴权区附近加:
```bash
# BYO-Key 凭据加密主密钥(base64 的 32 字节)。空则凭据功能不可用。
# 生成:python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
AGENT_CLOUD_CREDENTIAL_KEY=
```

- [ ] **Step 2: 后端全量回归** `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -q`(Expected: 全 passed;注意 conftest 需提供 credential_key,见 Task 3 Step 3)

- [ ] **Step 3: worker 回归** `cd services/worker && uv run pytest -q`(Expected: 全 passed)

- [ ] **Step 4: ruff** `cd <repo> && uv run ruff check services/backend services/worker`(Expected: clean;有则修)

- [ ] **Step 5: 前端回归** `cd frontend && npm run lint && npx vitest run`(Expected: 全绿)

- [ ] **Step 6: 提交**
```bash
git add .env.example
git commit -m "docs(.env.example): AGENT_CLOUD_CREDENTIAL_KEY (BYO-Key master key)"
```

---

## Task 8:live-verify + 对抗审查

- [ ] **Step 1: 配置 dev key** —— 给运行中的后端/worker 注入 `AGENT_CLOUD_CREDENTIAL_KEY`(生成一个 base64 32B),重启后端进程使其生效(参考会话里替换后端的做法)。
- [ ] **Step 2: 真机走查** —— 登录→设置抽屉 Provider Keys 加一个凭据(看到掩码、无明文回显)→ Agent 设置选该凭据保存 → 发一条消息看回合用上(可在 worker 日志/抓包确认用了该 base_url;或临时填一个会失败的 base_url 验证确实走了它)→ 删除凭据。截图 Provider Keys 区。
- [ ] **Step 3: 对抗审查** —— 派 Opus 子 agent 审 Plan C diff(`git diff` 范围),重点:密钥是否会落日志/回前端、解密时机、key_ref 跨用户、proto 字段是否误传 sandbox、迁移正确性、回退全局逻辑、前端掩码。按发现修复并复验。

---

## Self-Review

**Spec 覆盖**(§2/§5/§6.3/§8/§9/§10):
- §2 数据模型 provider_credentials ✓(Task 2);key_ref 复用已存在 ✓。
- §5 BYO-Key:crypto AES-GCM ✓(T1);credentials.py CRUD + 掩码 + 限本人 ✓(T3);回合按 key_ref 解密填 proto + 无则回退 ✓(T5);proto +2 字段、仅 BE→Worker ✓(T4);worker factory per-request ✓(T4);明文不落日志/不回前端、UI 掩码 ✓(T3 schema 不含明文、T5 不 log key)。
- §6.3 凭据 UI:Provider Keys 区(列表+表单+删除)✓(T6);agent 选凭据下拉 ✓(T6);账户菜单入口 ✓(T6)。
- §8 worker 小改 + sandbox 不变 ✓(T4;sandbox 不收 key)。
- §9 测试:加解密往返 ✓、CRUD+掩码 ✓、回合用本人 key + 回退 ✓、他人凭据 404 ✓、前端凭据 UI ✓、全栈回归 + tsc/ruff ✓、live 截图 ✓。
- §10 默认值:回退全局 ✓、env AES-GCM ✓、key_ref=credential id ✓。

**占位符扫描**:无 TBD/“类似上文”;关键代码均给全。conftest 注入 credential_key、db fixture 名、compaction 测试 settings 形参三处明确标注“按既有写法对齐”(因依赖现有 conftest,执行时一看即知)。

**类型一致**:`resolve_agent_key(db, key_ref, user_id, settings)->(str,str)` 在 T5 定义与 assemble/compaction 调用一致;factory `_effective_credentials(settings, api_key, base_url)->(str,str)` 与 server 调用顺序一致;proto `api_key=6/base_url=7` 与 server `request.agent.api_key/base_url`、assemble/compaction 填值一致;前端 `ProviderCredential{id,name,base_url,masked,created_at}` 与 schema `CredentialRead` 一致;`api.createCredential({name,base_url,api_key})` 与 `CredentialCreate` 一致;`openSettings(tab?)` 改动同步 store 接口/AgentSwitcher(`openSettings()` 仍合法,默认 "agent")。

**破坏性**:`ProviderFactory` 签名变更 —— 所有调用方在 T4 同改;`compact()` 加必填 `settings` —— 调用方 + 既有 compaction 测试在 T5 同改。
