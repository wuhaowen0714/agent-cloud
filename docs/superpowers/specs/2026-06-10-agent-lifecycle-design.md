# agent/会话生命周期(注册默认 + 一键新建 + 改名/删除)设计

**日期:** 2026-06-10
**状态:** 设计已批准,待写实现计划

## 目标

补齐 agent/会话的生命周期体验(用户三点诉求):
1. **注册即用**:新用户注册后自动拥有默认 agent(`main`)+ 一条默认会话,不必手动创建。
2. **一键新建 agent**:免填名称(默认 `Agent N`),入口更明显;新建后立刻进入行内改名态。
3. **行内改名 / 删除**:agent 行与会话行 hover 出 `…` 菜单(用户截图红框位置),支持重命名与删除(行内二次确认)。

已确认的三个决策:删除 agent **连带删除其全部会话**(确认文案写明);确认交互用**行内二次确认**(原位变红,再点执行);新建 agent 后**选中并立刻进入改名态**。

## 非目标(YAGNI)

- 批量删除、会话归档/置顶、拖拽排序、agent 复制。
- login 不补建默认 agent;存量用户不回填(仅注册时创建)。
- 不做软删除/回收站(硬删,确认文案承担提醒)。

---

## 1. 后端

### ① 注册默认 agent + 会话(`api/auth.py::register`)

创建 user 之后、`_issue`(它负责 commit)之前,同一事务内:

```
agent = AgentConfigRepository(db).create(AgentConfig(
    user_id=user.id, name="main",
    model=settings.default_agent_model, provider="openai",
))
SessionRepository(db).create_for(user.id, agent.id, None)   # title 空,沿用自动短名
```

- `config.py` 新增 `default_agent_model: str = "DeepSeek-V4-Pro"`(与前端 `DEFAULT_MODEL` 同值;两端各自常量,无运行时共享)。
- 事务原子:user/agent/session 同生共死;`_issue` 的 commit 一次落库。

### ② 会话重命名:`PATCH /sessions/{session_id}`

- body `{ "title": str }`(新 schema `SessionUpdate`);trim 后 1–200 字符,否则 422。
- `owned_session` 不属本人 → 404。返回 `SessionRead`。

### ③ 会话删除:`DELETE /sessions/{session_id}`

- `owned_session` → 404。
- **原子守卫**(与回合抢锁靠行锁天然串行,无 TOCTOU):

```sql
DELETE FROM sessions
WHERE id = :sid AND (status = 'idle' OR last_active_at < :cutoff)
```

`cutoff = now() - 600s`(与 `try_acquire` 同一租约语义:正常在跑挡住,crash 残留的 stale running 可删)。删除 0 行 → **409** `session busy`;否则 204。messages 已 `ondelete=CASCADE` 连带清除。

### ④ agent 删除:`DELETE /agent-configs/{agent_id}`

`owned_agent` → 404。同一事务依次:

1. 按 ③ 的同款原子守卫删除该 agent 的**全部会话**(`WHERE agent_config_id = :aid AND (idle OR 租约过期)`);随后查询仍存在的会话数,**> 0(有在跑的)→ 整体回滚,409** `agent busy`。
2. 清孤儿:`DELETE FROM memory_entries WHERE scope='agent' AND owner_id=:aid`;`DELETE FROM context_documents WHERE scope='agent' AND owner_id=:aid`(两表无 FK)。
3. 删 agent 行(`agent_skill_enables` 已 `ondelete=CASCADE` 自动清)→ 204。

> 现状盘点:agent 改名已有(`PATCH /agent-configs/{id}` name 字段);`sessions.agent_config_id` 是 `RESTRICT`,故必须先删会话;`messages.session_id` 是 `CASCADE`。

---

## 2. 前端

### 自动落位(通用改进)

侧栏 effect(agents/sessions 查询就绪后):
- `agentId === null` 且 agents 非空 → `setAgent(agents[0].id)`;
- 选中 agent 后 `sessionId === null` 且该 agent 有会话 → `setSession(最近创建的一条)`(列表末尾项)。

新注册用户登录即落在 `main` + 默认会话上;删除当前选中后的落位也复用此逻辑兜底。

### 一键新建 agent

- **入口**:去掉 Agents 分节头的小「＋」,改为列表**底部幽灵行「＋ 新建 Agent」**(与「新对话」同款视觉);空态按钮(还没有 agent)同样直创。
- 点击 → `createAgent({ name: nextAgentName(现有名), model: DEFAULT_MODEL, provider: "openai" })`;`nextAgentName`:取现有形如 `Agent k` 的最大 k+1(无则 1),纯函数放 `agentConfig.ts`。
- 成功 → 失效 agents 查询 + `setAgent(新 id)` + **该行进入改名态**(input autoFocus 全选默认名;Enter → `patchAgent({name})`;Esc/失焦 → 保留默认名)。
- **设置抽屉的「新建 Agent」表单删除**:`AgentSettings` 无选中 agent 时显示空态提示「在左侧选择或新建一个 agent」(原 `setAgent(null)+openSettings` 的新建流废弃)。

### 行内 `…` 菜单(`RowMenu` 共享组件)

`components/RowMenu.tsx`:`MoreHorizontal` 触发按钮(hover/选中显形,与 ⚙ 同款样式)+ `shadow-pop` 浮层菜单 + 行内二次确认状态机。

```ts
props: {
  items: {
    label: string            // 如 "重命名"
    danger?: boolean         // 红字
    confirmLabel?: string    // 有值 → 第一次点击变成此文案(红底),再点才执行
    onSelect: () => void | Promise<void>
  }[]
  ariaLabel: string          // 触发按钮可达名,如 "test 更多操作"
}
```

- 点外面 / Esc 关闭并复位确认态;`onSelect` 抛错(如 409)→ 菜单原位短暂红字「进行中,无法删除」(~2s)后复位。
- **agent 行**:`[⚙ 设置(保留)] [… 菜单: 重命名 / 删除(确认文案「连同全部会话删除?」)]`。
- **会话行**:`[… 菜单: 重命名 / 删除(确认文案「确认删除?」)]`。

### 行内重命名

行内容临时替换为 `<input>`(autoFocus、全选当前名);Enter 提交(agent → `patchAgent({name})`,会话 → `patchSession({title})`,trim 空则忽略),Esc/失焦取消。提交后失效对应查询。

### 删除后的落位

- 删 agent:`deleteAgent(id)` → 失效 agents + sessions;若删的是当前选中 → `setAgent(剩余第一个 ?? null)`(自动落位 effect 兜底会话)。
- 删会话:`deleteSession(id)` → 失效 sessions;若是当前选中 → `setSession(null)`。

### api/client 新增

```ts
patchSession: (id, body: { title: string }) => PATCH /sessions/{id} → Session
deleteSession: (id) => DELETE /sessions/{id} → void
deleteAgent: (id) => DELETE /agent-configs/{id} → void
```

---

## 3. 测试

**后端 pytest**:
- 注册:`/auth/register` 后 listAgents 含 `main`(模型 = default_agent_model)、listSessions 恰 1 条挂它;同一事务(注册 409 时无残留 agent)。
- PATCH session:改名生效;空/超长 422;他人 404。
- DELETE session:204 后列表消失、消息连带删;`running`(租约内)→ 409;stale running(租约过期)可删;他人 404。
- DELETE agent:连带会话/消息/agent 级记忆/文档全清,`agent_skill_enables` 级联;任一会话 running → 409 且**整体回滚**(会话仍在);他人 404。

**前端 vitest**:
- `nextAgentName`:空表→Agent 1;`["main","Agent 2","Agent 9"]`→Agent 10;非模式名忽略。
- AgentList:点「＋ 新建 Agent」→ createAgent(默认名/DEFAULT_MODEL/openai)→ 行变 input(改名态)→ Enter 调 patchAgent;Esc 保留默认名。
- RowMenu:菜单展开;重命名回调;删除需两次点击(第一次变确认文案,点外面复位);onSelect reject → 显示「进行中,无法删除」。
- SessionList:重命名调 patchSession;删除调 deleteSession;删当前选中 → setSession(null)。
- 删当前选中 agent → 自动选剩余第一个。
- 自动落位:agents 就绪且 agentId null → setAgent(第一个)。
- AgentSettings:无选中时显示空态(创建表单已移除,旧「创建预设模型」用例随之删除——该行为转由 AgentList 用例覆盖)。

---

## 4. 受影响文件

**后端**:`config.py`(默认模型)、`api/auth.py`(注册建默认)、`schemas/session.py`(+SessionUpdate)、`api/sessions.py`(+PATCH/+DELETE)、`api/agent_configs.py`(+DELETE)、`repositories/session.py`(原子守卫删除助手)、tests(`test_auth_defaults.py`/`test_session_lifecycle_api.py`/`test_agent_delete_api.py` 或并入现有文件)。

**前端**:`api/client.ts`(三个新调用)、`agentConfig.ts`(+nextAgentName)、`components/RowMenu.tsx`(新)、`AgentList.tsx`(幽灵新建行/改名态/菜单)、`SessionList.tsx`(菜单/改名)、`Sidebar.tsx` 或新 hook(自动落位)、`settings/AgentSettings.tsx`(移除创建表单)+ 各测试。
