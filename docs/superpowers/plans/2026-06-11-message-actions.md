# 消息级操作(复制/回滚/Fork)Implementation Plan

> **For agentic workers:** controller 直接 TDD 实现(子 agent 仅审查)。每步小步快跑,跑测试,提交。

**Goal:** 消息 hover 操作——复制(用户+助手)、回滚会话到某用户消息之前(原地销毁性 + 回填输入框)、从某用户消息 fork 出新会话(非销毁 + 回填),回滚/fork 不动文件。

**Architecture:** 扁平硬删 + 复制式 fork,零 schema 改动。回滚 `DELETE` seq≥target 后缀并修压缩/记忆游标(与回合同锁);fork 复制 seq<target 前缀进新会话。前端 hover 按钮 → 调 API → 回填经 store `composerDraft`。

**Tech Stack:** FastAPI + SQLAlchemy async(backend);React19 + zustand + RTL/vitest(frontend)。

参考实现:`api/sessions.py` 的 `compact_session`(锁模式)、`repositories/session.py`(try_acquire/release)、`repositories/message.py`、`blocks.ts` `messagesToTurns`(`turn.id` = 用户消息 id)、`ChatView` 的 `onRetry` 下传模式。

---

## File Structure

**Backend**
- Modify `services/backend/src/agent_cloud_backend/schemas/session.py` — 加 `RollbackRequest`/`RollbackResult`/`ForkRequest`/`ForkResult`。
- Modify `services/backend/src/agent_cloud_backend/repositories/message.py` — 加 `get_in_session`、`delete_from_seq`、`copy_prefix_to`。
- Modify `services/backend/src/agent_cloud_backend/repositories/session.py` — 加 `apply_rollback_cursors`。
- Modify `services/backend/src/agent_cloud_backend/api/sessions.py` — 加 `rollback_session`、`fork_session` 端点。
- Test `services/backend/tests/test_message_actions.py`(新建)。

**Frontend**
- Modify `frontend/src/store.ts` — `composerDraft` + `setComposerDraft`,logout/切用户重置。
- Modify `frontend/src/api/client.ts` — `rollbackSession`、`forkSession`。
- Create `frontend/src/components/MessageActions.tsx` — hover 图标按钮行。
- Modify `frontend/src/components/MessageList.tsx` — 用户/助手气泡接 MessageActions。
- Modify `frontend/src/components/Composer.tsx` — 消费 `composerDraft`。
- Modify `frontend/src/components/ChatView.tsx` — `onRollback`/`onFork` 下传。
- Tests:`store.test.ts`、`MessageActions.test.tsx`(新)、`Composer.test.tsx`、`api/client` 处。

---

## Task 1: 后端回滚端点

**Files:** schemas/session.py, repositories/message.py, repositories/session.py, api/sessions.py, tests/test_message_actions.py

- [ ] **Step 1: 失败测试**(`tests/test_message_actions.py`)

```python
import pytest

@pytest.mark.asyncio
async def test_rollback_deletes_suffix_and_returns_user_text(client, make_session_with_messages):
    # 历史:u0,a0,u1,a1,u2  (seq 0..4)
    sid, msgs = await make_session_with_messages(["u0","a0","u1","a1","u2"])
    target = msgs[2]  # u1 (seq=2)
    r = await client.post(f"/sessions/{sid}/rollback", json={"message_id": str(target.id)})
    assert r.status_code == 200
    assert r.json()["user_text"] == "u1"
    assert r.json()["deleted_count"] == 3  # u1,a1,u2
    listed = (await client.get(f"/sessions/{sid}/messages")).json()
    assert [m["content"]["text"] for m in listed] == ["u0", "a0"]
```

(`make_session_with_messages` fixture:按列表交替 user/assistant 角色 append 消息,返回 session_id + Message 行。放进 `tests/conftest.py` 或本文件;角色按 index 偶=user 奇=assistant。)

- [ ] **Step 2: 跑测试确认失败** — `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_message_actions.py -k rollback_deletes -x`,预期 404(端点不存在)。

- [ ] **Step 3: schema**(schemas/session.py 追加)

```python
class RollbackRequest(BaseModel):
    message_id: uuid.UUID

class RollbackResult(BaseModel):
    deleted_count: int
    user_text: str

class ForkRequest(BaseModel):
    message_id: uuid.UUID

class ForkResult(BaseModel):
    new_session_id: uuid.UUID
    user_text: str
```

- [ ] **Step 4: repo 方法**(repositories/message.py 追加)

```python
    async def get_in_session(self, session_id: uuid.UUID, message_id: uuid.UUID) -> Message | None:
        m = await self.session.get(Message, message_id)
        return m if m is not None and m.session_id == session_id else None

    async def delete_from_seq(self, session_id: uuid.UUID, target_seq: int) -> int:
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(Message).where(Message.session_id == session_id, Message.seq >= target_seq)
        )
        return result.rowcount
```

repositories/session.py 追加(用裸 UPDATE,**不**碰 status——避免提交 stale ORM 把锁释放掉):

```python
    async def apply_rollback_cursors(self, session_id: uuid.UUID, target_seq: int) -> None:
        """回滚后修游标:摘要若折叠了被删消息则丢弃;记忆游标钳到 target-1;清 last_context_tokens。
        在持锁的同一事务内调用(get 会读到 try_acquire 提交后的新状态)。"""
        s = await self.session.get(Session, session_id)
        drop_summary = target_seq <= s.summary_through_seq
        await self.session.execute(
            update(Session).where(Session.id == session_id).values(
                summary="" if drop_summary else s.summary,
                summary_through_seq=-1 if drop_summary else s.summary_through_seq,
                memory_through_seq=min(s.memory_through_seq, target_seq - 1),
                last_context_tokens=None,
            )
        )
```

- [ ] **Step 5: 端点**(api/sessions.py;import `Message`、`MessageRepository`、`RollbackRequest`、`RollbackResult`、`logging`)

```python
@router.post("/{session_id}/rollback", response_model=RollbackResult)
async def rollback_session(
    session_id: uuid.UUID,
    body: RollbackRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """回到该用户消息之前:删 seq>=target 的全部消息 + 修游标。与回合/压缩同锁。"""
    await owned_session(session_id, user.id, session)  # 404
    repo = MessageRepository(session)
    msg = await repo.get_in_session(session_id, body.message_id)
    if msg is None or msg.role != "user":
        raise HTTPException(status_code=422, detail="message must be a user message in this session")
    target = msg.seq
    user_text = msg.content["text"]
    sess_repo = SessionRepository(session)
    if not await sess_repo.try_acquire(session_id):
        await session.rollback()
        raise HTTPException(status_code=409, detail="session is busy")
    await session.commit()
    try:
        deleted = await repo.delete_from_seq(session_id, target)
        await sess_repo.apply_rollback_cursors(session_id, target)
        await session.commit()
        return RollbackResult(deleted_count=deleted, user_text=user_text)
    finally:
        try:
            await session.rollback()
            await sess_repo.release(session_id)
            await session.commit()
        except Exception:
            logging.getLogger(__name__).exception("rollback: failed to release lock %s", session_id)
```

- [ ] **Step 6: 跑测试通过** — 同 Step 2 命令,预期 PASS。

- [ ] **Step 7: 加边界测试并通过**

```python
@pytest.mark.asyncio
async def test_rollback_resets_summary_when_target_within_summary(client, db_session, make_session_with_messages):
    sid, msgs = await make_session_with_messages(["u0","a0","u1","a1"])
    # 模拟压缩到 seq=2:summary_through_seq=2, summary="S"
    await set_session_compaction(db_session, sid, summary="S", summary_through_seq=2, memory_through_seq=2)
    await client.post(f"/sessions/{sid}/rollback", json={"message_id": str(msgs[2].id)})  # target=2 <= 2
    s = await reload_session(db_session, sid)
    assert s.summary == "" and s.summary_through_seq == -1
    assert s.memory_through_seq == 1  # min(2, 2-1)

@pytest.mark.asyncio
async def test_rollback_409_when_running(client, db_session, make_session_with_messages):
    sid, msgs = await make_session_with_messages(["u0","a0","u1"])
    await set_session_status(db_session, sid, "running")  # 直接置 running
    r = await client.post(f"/sessions/{sid}/rollback", json={"message_id": str(msgs[0].id)})
    assert r.status_code == 409

@pytest.mark.asyncio
async def test_rollback_422_on_assistant_or_foreign_message(client, make_session_with_messages):
    sid, msgs = await make_session_with_messages(["u0","a0"])
    r = await client.post(f"/sessions/{sid}/rollback", json={"message_id": str(msgs[1].id)})  # a0
    assert r.status_code == 422
```

(helper `set_session_compaction`/`set_session_status`/`reload_session`:直接 UPDATE/refresh session 行。`test_rollback_409_when_running`:置 running 后 try_acquire 因 lease 未过期会失败 → 409。注意 last_active_at 要置为 now 以确保 lease 未过期。)

- [ ] **Step 8: 提交** — `git add -A && git commit -m "feat(backend): rollback endpoint — delete message suffix + fix compaction/memory cursors"`

---

## Task 2: 后端 Fork 端点

**Files:** repositories/message.py, api/sessions.py, tests/test_message_actions.py

- [ ] **Step 1: 失败测试**

```python
@pytest.mark.asyncio
async def test_fork_copies_prefix_to_new_session(client, make_session_with_messages):
    sid, msgs = await make_session_with_messages(["u0","a0","u1","a1","u2"])
    target = msgs[2]  # u1 seq=2
    r = await client.post(f"/sessions/{sid}/fork", json={"message_id": str(target.id)})
    assert r.status_code == 200
    new_id = r.json()["new_session_id"]
    assert r.json()["user_text"] == "u1"
    assert new_id != str(sid)
    new_msgs = (await client.get(f"/sessions/{new_id}/messages")).json()
    assert [m["content"]["text"] for m in new_msgs] == ["u0", "a0"]  # seq<2
    orig_msgs = (await client.get(f"/sessions/{sid}/messages")).json()
    assert len(orig_msgs) == 5  # 原会话不变
```

- [ ] **Step 2: 跑测试确认失败** — `... uv run pytest tests/test_message_actions.py -k fork_copies -x`,预期 404。

- [ ] **Step 3: repo 复制方法**(repositories/message.py 追加)

```python
    async def copy_prefix_to(self, src_session_id: uuid.UUID, dst_session_id: uuid.UUID,
                             below_seq: int) -> None:
        rows = await self.list_by_session(src_session_id)
        for m in rows:
            if m.seq >= below_seq:
                continue
            self.session.add(Message(
                session_id=dst_session_id, seq=m.seq, role=m.role,
                content=m.content, model=m.model, tokens=m.tokens,
            ))
        await self.session.flush()
```

- [ ] **Step 4: 端点**(api/sessions.py;import `Session` model、`ForkRequest`、`ForkResult`)

```python
@router.post("/{session_id}/fork", response_model=ForkResult)
async def fork_session(
    session_id: uuid.UUID,
    body: ForkRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """从该用户消息之前复制出新会话(原会话不动);只读原会话,允许其在跑。"""
    s = await owned_session(session_id, user.id, session)  # 404
    repo = MessageRepository(session)
    msg = await repo.get_in_session(session_id, body.message_id)
    if msg is None or msg.role != "user":
        raise HTTPException(status_code=422, detail="message must be a user message in this session")
    target = msg.seq
    user_text = msg.content["text"]
    keep_summary = s.summary_through_seq < target
    new = Session(
        user_id=s.user_id, agent_config_id=s.agent_config_id, work_subdir=s.work_subdir,
        title=(f"{s.title}(分支)" if s.title else None),
        summary=(s.summary if keep_summary else ""),
        summary_through_seq=(s.summary_through_seq if keep_summary else -1),
        memory_through_seq=min(s.memory_through_seq, target - 1),
    )
    session.add(new)
    await session.flush()  # 拿 new.id
    await repo.copy_prefix_to(session_id, new.id, target)
    await session.commit()
    return ForkResult(new_session_id=new.id, user_text=user_text)
```

- [ ] **Step 5: 跑测试通过** — 同 Step 2,预期 PASS。

- [ ] **Step 6: 加边界测试并通过**

```python
@pytest.mark.asyncio
async def test_fork_title_and_summary_carry(client, db_session, make_session_with_messages):
    sid, msgs = await make_session_with_messages(["u0","a0","u1","a1"])
    await set_session_title(db_session, sid, "原标题")
    await set_session_compaction(db_session, sid, summary="S", summary_through_seq=1, memory_through_seq=1)
    r = await client.post(f"/sessions/{sid}/fork", json={"message_id": str(msgs[2].id)})  # target=2 > 1
    new = await reload_session(db_session, r.json()["new_session_id"])
    assert new.title == "原标题(分支)"
    assert new.summary == "S" and new.summary_through_seq == 1  # 1 < 2 → 带过去
```

- [ ] **Step 7: 提交** — `git add -A && git commit -m "feat(backend): fork endpoint — copy message prefix into a new session"`

---

## Task 3: 前端 store composerDraft + api client

**Files:** store.ts, store.test.ts, api/client.ts

- [ ] **Step 1: 失败测试**(store.test.ts 追加)

```typescript
it("composerDraft set/clear,logout 重置", () => {
  s().setComposerDraft("回填文本")
  expect(s().composerDraft).toBe("回填文本")
  s().setComposerDraft(null)
  expect(s().composerDraft).toBeNull()
  s().setComposerDraft("x"); s().logout()
  expect(s().composerDraft).toBeNull()
})
```

- [ ] **Step 2: 跑失败** — `cd frontend && npx vitest run src/store.test.ts -t composerDraft`,预期 fail(无该字段/方法)。

- [ ] **Step 3: 实现**(store.ts)
  - `AppState` 加 `composerDraft: string | null` + `setComposerDraft: (text: string | null) => void`。
  - 初值 `composerDraft: null`。
  - action:`setComposerDraft: (text) => set({ composerDraft: text })`。
  - `logout` 与 setAuth 切用户分支的 `set({...})` 加 `composerDraft: null`。

- [ ] **Step 4: 跑通过** — 同 Step 2。

- [ ] **Step 5: api client**(api/client.ts,session 段追加)

```typescript
  rollbackSession: (id: string, messageId: string) =>
    http<{ deleted_count: number; user_text: string }>(
      `/sessions/${id}/rollback`, { method: "POST", body: JSON.stringify({ message_id: messageId }) }),
  forkSession: (id: string, messageId: string) =>
    http<{ new_session_id: string; user_text: string }>(
      `/sessions/${id}/fork`, { method: "POST", body: JSON.stringify({ message_id: messageId }) }),
```

- [ ] **Step 6: lint + 提交** — `npm run lint` 干净;`git commit -m "feat(frontend): store composerDraft + rollback/fork api client"`

---

## Task 4: 前端 MessageActions + 接线 + Composer 回填

**Files:** MessageActions.tsx(新), MessageList.tsx, ChatView.tsx, Composer.tsx, MessageActions.test.tsx(新), Composer.test.tsx

- [ ] **Step 1: 失败测试**(MessageActions.test.tsx,新)

```tsx
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { MessageActions } from "./MessageActions"

describe("MessageActions", () => {
  it("用户消息:复制/回滚/fork 三个;助手消息:仅复制", () => {
    const { rerender } = render(<MessageActions text="hi" onRollback={() => {}} onFork={() => {}} />)
    expect(screen.getByRole("button", { name: "复制" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "回滚到此处" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Fork 新会话" })).toBeInTheDocument()
    rerender(<MessageActions text="ans" />)
    expect(screen.getByRole("button", { name: "复制" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "回滚到此处" })).not.toBeInTheDocument()
  })

  it("复制调 clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<MessageActions text="hello" />)
    fireEvent.click(screen.getByRole("button", { name: "复制" }))
    expect(writeText).toHaveBeenCalledWith("hello")
  })
})
```

- [ ] **Step 2: 跑失败** — `npx vitest run src/components/MessageActions.test.tsx`,预期 fail(组件不存在)。

- [ ] **Step 3: 实现 MessageActions.tsx**(用 lucide 图标:`Copy`、`Undo2`、`GitBranch`;hover 由父级 `group` 控制透明度)

```tsx
import { Copy, GitBranch, Undo2 } from "lucide-react"

export function MessageActions({
  text, onRollback, onFork,
}: { text: string; onRollback?: () => void; onFork?: () => void }) {
  const btn = "rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
  return (
    <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
      <button type="button" aria-label="复制" className={btn}
        onClick={() => void navigator.clipboard?.writeText(text)}>
        <Copy className="h-3.5 w-3.5" />
      </button>
      {onRollback && (
        <button type="button" aria-label="回滚到此处" className={btn} onClick={onRollback}>
          <Undo2 className="h-3.5 w-3.5" />
        </button>
      )}
      {onFork && (
        <button type="button" aria-label="Fork 新会话" className={btn} onClick={onFork}>
          <GitBranch className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 4: 跑 MessageActions 测试通过** — 同 Step 2。

- [ ] **Step 5: MessageList 接线**(historical turns 段:`turn.id` = 用户消息 id;用户气泡那块外层加 `group`,内嵌 `<MessageActions text={turn.userText} onRollback={() => onRollback?.(turn.id)} onFork={() => onFork?.(turn.id)} />`;助手气泡那块外层加 `group`,内嵌 `<MessageActions text={assistantText(turn)} />`,其中 `assistantText` = `turn.blocks.filter(b => b.kind==="text").map(b => b.text).join("\n")`。MessageList props 加 `onRollback?: (messageId: string) => void`、`onFork?: (messageId: string) => void`。live 块不加按钮。)

- [ ] **Step 6: ChatView 接线**(加 `onRollback`/`onFork` 传给 MessageList)

```tsx
const setComposerDraft = useStore((s) => s.setComposerDraft)
const onRollback = async (messageId: string) => {
  const sid = sessionId
  try {
    const r = await api.rollbackSession(sid, messageId)
    await qc.invalidateQueries({ queryKey: ["messages", sid] })
    await qc.invalidateQueries({ queryKey: ["sessions"] })
    clearLive()
    setComposerDraft(r.user_text)
  } catch (e) {
    // 409 等:轻提示(复用现有 flash/通知途径或 alert 最简)
  }
}
const onFork = async (messageId: string) => {
  const r = await api.forkSession(sessionId, messageId)
  await qc.invalidateQueries({ queryKey: ["sessions"] })
  setSession(r.new_session_id)
  setComposerDraft(r.user_text)
}
// <MessageList ... onRollback={onRollback} onFork={onFork} />
```

(`clearLive`、`setSession` 已在 store;`setSession` 已 import?ChatView 现有 `live` 相关,需补 `const setSession = useStore(s => s.setSession)`。)

- [ ] **Step 7: Composer 消费 composerDraft**(Composer.tsx)

```tsx
const composerDraft = useStore((s) => s.composerDraft)
const setComposerDraft = useStore((s) => s.setComposerDraft)
useEffect(() => {
  if (composerDraft != null) {
    setText(composerDraft)
    setComposerDraft(null)
    requestAnimationFrame(() => taRef.current?.focus())
  }
}, [composerDraft, setComposerDraft])
```

- [ ] **Step 8: Composer 回填测试**(Composer.test.tsx 追加)

```tsx
it("composerDraft 非空 → 写入输入框并清空(消费一次)", () => {
  setup()
  act(() => { useStore.getState().setComposerDraft("回填的问题") })
  expect(box()).toHaveValue("回填的问题")
  expect(useStore.getState().composerDraft).toBeNull()
})
```

- [ ] **Step 9: 全前端回归 + lint** — `npm test` 全绿、`npm run lint` 干净。

- [ ] **Step 10: 提交** — `git commit -m "feat(frontend): message hover actions (copy/rollback/fork) + composer refill"`

---

## Task 5: 回归 + Fable 5 审查 + PR

- [ ] **Step 1: 后端全套** — `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q` 全绿。
- [ ] **Step 2: 前端全套** — `cd frontend && npm run lint && npm test` 全绿。
- [ ] **Step 3: Fable 5 对抗审查**(model: fable)——重点:回滚锁/游标正确性(stale ORM 不clobber status、target≤summary_through_seq 重置、memory 钳位、seq 复用与游标冲突)、fork 复制完整性 + 原会话不变 + 共享 workspace 语义、所有权/角色校验、前端回填竞态(composerDraft 与用户已输入文本)、复制内容。
- [ ] **Step 4: 修复审查问题**(TDD)。
- [ ] **Step 5: PR + CI 绿 + 合并**(用户确认)。

---

## Self-Review

**Spec 覆盖:** 复制(Task4 用户+助手)✓;回滚语义+游标+锁(Task1)✓;fork 语义+标题+游标(Task2)✓;composerDraft 回填(Task3/4)✓;错误处理 409/422/404(Task1/2 测试)✓;测试矩阵(各 Task)✓;文件不动(无文件操作代码,fork 复制 work_subdir)✓。

**占位扫描:** 无 TBD;各步含真实代码/命令。ChatView onRollback 的 catch 注释为"轻提示",Task4 Step6 用最简提示即可(非占位——明确可用 alert 或现有通知)。

**类型一致:** `RollbackResult{deleted_count,user_text}`、`ForkResult{new_session_id,user_text}` 前后端字段名一致;`turn.id`=用户消息 id 已由 blocks.ts 证实;`MessageActions` props(text/onRollback?/onFork?)在 Task4 内自洽。
