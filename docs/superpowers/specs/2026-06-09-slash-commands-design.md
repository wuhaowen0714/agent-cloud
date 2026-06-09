# 斜杠命令面板(`/`)设计

**日期:** 2026-06-09
**状态:** 设计已批准,待写实现计划

## 目标

在聊天输入框(Composer)里,当文本**以 `/` 开头**时弹出一个预设命令面板(对齐 Codex 的斜杠菜单)。命令是**纯客户端动作,绝不发给 LLM**:压缩上下文、看状态、开新会话、切模型、跳设置等。面板可键盘驱动、可鼠标点选,易扩展。

## 非目标(YAGNI)

- 按会话覆盖模型(模型仍是按 agent 存的自由文本)
- 命令历史 / 最近使用排序
- 模糊匹配(只做前缀匹配)
- 命令级权限
- 把命令作为消息发给 LLM(它们永远是本地动作)

---

## 交互模型

输入框文本驱动一个三态解析:

1. **命令模式** — 文本匹配 `^/(\w*)$`(斜杠 + word 字符、无空格)**且**至少一个命令名以该前缀开头。
   - 面板列出所有「名字或别名以该前缀开头」的命令。纯 `/` → 列全部。
   - 边打边过滤(`/co` → 只剩 compact)。
2. **参数模式** — 文本匹配 `^/(<带参命令名>)\s(.*)$`(目前只有 `model`)。
   - 面板改列「该命令的参数建议」(见 `/model`),按空格后的文本过滤,并**始终**附一条「应用 '<已输入文本>'」(已输入为空时不显示这条)。
3. **直通** — 其它情况(以 `/` 开头但匹配不到命令,如 `/usr/bin/python`;或 Esc 关掉面板后)→ 面板不出现,Enter 当**普通消息**发送。

### 键盘

| 键 | 面板开 | 面板关 |
|---|---|---|
| ↑ / ↓ | 移动高亮(到边界停住,不回绕) | 透传给 textarea |
| Enter | 执行/提交高亮项 | 发送消息(原行为) |
| Tab | 同 Enter(执行/提交高亮项),`preventDefault` | 默认行为 |
| Esc | 关面板、保留文本(此后该文本走直通) | 无 |
| 其它输入 | 重新解析、面板内容随之更新 | — |

- 鼠标点击命令/建议项 = 执行/提交。
- 点面板外收起(复用 `SelectMenu` 的 `pointerdown` 监听范式)。
- 命令模式按 Enter/Tab:
  - **无参命令** → 执行,清空输入,关面板。
  - **带参命令**(`/model`) → 把输入补成 `"/model "`(命令名 + 空格),进入参数模式;**不**执行。

### 直通的边界判定

- 触发命令面板的充要条件:`^/(\w*)$` 且有命令前缀匹配。`/usr/bin/python`(斜杠后含 `/`)不匹配 `^/\w*$` → 永远直通,可正常作为消息发送。
- 用户想把恰好是命令前缀的文本(如 `/status`)当普通消息发:Esc 关面板后 Enter 即发。

---

## v1 命令集

### 核心命令

| 命令 | 别名 | 作用 | 落点 | 反馈 |
|---|---|---|---|---|
| `/compact` | — | 立即压缩当前会话上下文 | **新后端接口** `POST /sessions/{id}/compact` | flash「已压缩」/「暂无可压缩内容」/「失败」 |
| `/status` | — | 当前 agent(名/模型/provider)、会话(标题 + 短 id)、消息数 | 纯前端读 store + query 缓存 | 弹只读状态卡 |
| `/new` | — | 用当前 agent 开**新会话**并切过去(**非破坏**:旧会话保留在历史) | `createSession` + `setSession` + 失效 sessions 查询 | 切到空会话 |
| `/model` | — | 改**当前 agent** 的模型(**持久化**,影响该 agent 所有会话) | `patchAgent({model})` + 失效 agents 查询 | flash「已切到 <model>」 |
| `/help` | — | 列出全部命令 | 纯前端 | 状态卡式命令列表 |

### 导航命令(各一行 `openSettings(tab)`)

| 命令 | 落点 |
|---|---|
| `/settings` | `openSettings("agent")` |
| `/memory` | `openSettings("memory")` |
| `/skills` | `openSettings("skills")` |
| `/keys` | `openSettings("keys")` |

> `settingsTab` 类型已是 `"agent" | "skills" | "keys" | "memory"`,四个 tab 一一对应。

### `/model` 的参数建议

- 建议来源:`api.listAgents()`(或其 react-query 缓存)里所有 agent 的 `model` 字段,**去掉空串后去重保留全部值**(包含当前 agent 当前 model);按空格后输入做前缀过滤。
- 始终附一条「应用 '<已输入文本>'」:支持输入任意新模型字符串(自由文本)。
- 选中任一项 → `patchAgent(agentId, { model })`,成功后失效 `["agents"]` 查询、flash 反馈。

---

## 前端架构

**原则:Composer 自包含,对外 props 不变(`disabled/onSend/onStop`),ChatView 零改动。**(方案 A;方案 B「把命令执行提到 ChatView 往下传」会让 props 膨胀、Composer 不自洽,弃用。)

### 新增文件

#### `src/components/slash/commands.ts` — 纯注册表

```ts
export interface SlashContext {
  sessionId: string
  agentId: string | null
  newSession: () => Promise<void>          // create + switch
  setModel: (model: string) => Promise<void>
  compact: () => Promise<void>
  modelSuggestions: () => string[]         // 去重后的候选模型
  status: () => StatusInfo                  // 供 /status 卡渲染
  openSettings: (tab: SettingsTab) => void
  notify: (msg: string) => void            // 一行 flash
  showStatus: () => void                   // 打开状态卡
  showHelp: () => void                     // 打开 help 卡
}

export interface SlashCommand {
  name: string                 // 不含斜杠,如 "compact"
  aliases?: string[]
  title: string                // 中文标题
  hint: string                 // 右侧说明
  needsArg?: boolean           // true → Enter/Tab 进参数模式
  run?: (ctx: SlashContext) => void | Promise<void>          // 无参执行
  suggestions?: (ctx: SlashContext, arg: string) => string[] // 参数模式候选
  runWithArg?: (ctx: SlashContext, arg: string) => void | Promise<void>
}

export const COMMANDS: SlashCommand[]
```

- 纯数据 + 纯函数,不引 React;便于单测。
- 解析辅助:`parseInput(text): { mode: "command", prefix } | { mode: "arg", command, arg } | { mode: "none" }` 也放这里(纯函数,重点单测)。
- 过滤辅助:`matchCommands(prefix): SlashCommand[]`(名字或别名前缀匹配)。

#### `src/components/slash/useSlashCommands.ts` — 装配 ctx(React 层)

- `useStore` 取 `sessionId/agentId/setSession/openSettings`。
- `useQueryClient`:读 `["messages", sessionId]` 缓存算消息数;失效 `["sessions"]`/`["agents"]`。
- `api`:`createSession/patchAgent/compactSession/listAgents`。
- 返回 `SlashContext`。flash / status-card / help-card 的开关状态由 Composer 本地 state 管,hook 通过回调把 `notify/showStatus/showHelp` 接上。

#### `src/components/slash/SlashPalette.tsx` — 纯展示浮层

- props:`items`(命令或字符串建议)、`selectedIndex`、`mode`、`onSelect(index)`、`onHover(index)`。
- 样式沿用 `SelectMenu`:`absolute … z-30 … rounded-xl border border-slate-200 bg-white p-1.5 shadow-pop`,定位在 composer 输入框**上方**(`bottom-full mb-2`)。
- 每项:标题 + 右侧 hint;高亮项 `bg-slate-100`;`role="listbox"`/`option`、`aria-selected`。
- 不自管键盘 —— 键盘在 Composer 统一路由(见下)。

#### `src/components/slash/StatusCard.tsx` — 只读卡 + flash 通知槽

- 一个组件承载 composer 上方的「通知槽」,两种内容:
  - **status / help**:富卡(状态卡列 agent/会话/消息数;help 卡列命令表)。
  - **flash**:一行结果(compact/model/new 的成功或错误)。
- Esc / 点外面 / 下次输入变更 → 关闭。flash 可选 setTimeout 自动消失(组件内,非纯函数模块)。

### 改动文件

#### `src/components/Composer.tsx`

- 现有:`text` state + `<Textarea>` + 发送/停止按钮。
- 新增:
  - `const ctx = useSlashCommands({ notify, showStatus, showHelp })`
  - 由 `text` 派生 `parseInput(text)` → 决定面板模式与 items、维护 `selectedIndex`。
  - `onKeyDown` 路由:面板开时拦截 ↑↓/Enter/Tab/Esc;面板关时保持原逻辑(Enter 发送、Shift+Enter 换行)。
  - 渲染 `<SlashPalette>`(面板开时)与 `<StatusCard>`(通知槽,有内容时)。
  - 执行命令后:无参 → `setText("")`;`/model` 提交参数 → `setText("")`。
- 仍然:`disabled`(streaming 中)时输入框禁用,自然不会触发面板。

---

## 后端 `/compact` 接口

### 契约

```
POST /api/sessions/{session_id}/compact
→ 200 { "compacted": bool }
→ 404 会话不属本人 / 不存在(不泄漏存在性)
→ 409 会话正忙(回合进行中)
```

### 实现(`api/sessions.py` 新增 handler)

```python
@router.post("/{session_id}/compact")
async def compact_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    await owned_session(session_id, user.id, session)          # 404
    acquired = await SessionRepository(session).try_acquire(session_id)
    await session.commit()
    if not acquired:
        raise HTTPException(status_code=409, detail="session busy")
    try:
        progressed = await compact(
            session_id,
            worker_endpoint=settings.worker_endpoint,
            keep_recent=settings.compaction_keep_recent,
            settings=settings,
        )
    finally:
        async with get_sessionmaker()() as db:                 # 独立 db release
            await SessionRepository(db).release(session_id)
            await db.commit()
    return {"compacted": progressed}
```

要点:
- 复用已有 `turn/compaction.py::compact`,用**常规** `keep_recent`(不用 `force_compact` 的「只留 1 条」激进折叠)。
- `try_acquire`/`release` 与回合用**同一把会话锁**(`status idle↔running`),所以手动压缩与进行中回合**不可能并发**改 `session.summary`。
- 压缩只推进 `summary_through_seq`、改 `summary`,**不删消息**;`listMessages` 仍返回全量 → **前端转录区无变化**,反馈靠 flash。
- best-effort 失败(`compact` 内部已 try/except 返回 False)→ `compacted: false`,前端 flash「暂无可压缩内容」。

### 前端 api

```ts
// api/client.ts
compactSession: (id: string) =>
  http<{ compacted: boolean }>(`/sessions/${id}/compact`, { method: "POST" }),
```

---

## 数据流(逐命令)

- `/compact` → `ctx.compact()` → `api.compactSession(sessionId)` → flash(`compacted ? "已压缩" : "暂无可压缩内容"`);抛错 → flash「压缩失败」。
- `/status` → `ctx.showStatus()` → StatusCard 读 `ctx.status()`(agent 从 `listAgents` 缓存按 `agentId` 找;会话标题/短 id 从 sessions 缓存;消息数从 `["messages", sessionId]` 缓存 `length`)。
- `/new` → `ctx.newSession()` → `api.createSession({ agent_config_id: agentId })` → `setSession(new.id)` → 失效 `["sessions"]` → flash「已新建会话」。
- `/model <m>` → `ctx.setModel(m)` → `api.patchAgent(agentId, { model: m })` → 失效 `["agents"]` → flash「已切到 m」。
- `/help` → `ctx.showHelp()` → StatusCard 列 `COMMANDS`。
- `/settings|/memory|/skills|/keys` → `ctx.openSettings(tab)`。

---

## 测试

### 后端(pytest,`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker"`)

- `test_compact_endpoint_owned_404`:他人会话 → 404。
- `test_compact_endpoint_busy_409`:会话 `running`(try_acquire 占着)→ 409。
- `test_compact_endpoint_progress_true`:够长历史 → `compacted: true` 且 `summary_through_seq` 推进。
- `test_compact_endpoint_nothing_to_compact`:历史不足 → `compacted: false`。
- `test_compact_endpoint_releases_lock`:执行后会话回到 `idle`(即便 compact 内部失败也 release)。

### 前端(vitest)

- `commands.test.ts`:`parseInput` 三态(command/arg/none,含 `/usr/bin/...` 直通、`/model ` 进参数);`matchCommands` 前缀匹配(名字 + 别名);模型建议去重。
- `Composer.test.tsx`(扩展现有):
  - 打 `/` 弹面板列全部;打 `/co` 只剩 compact。
  - ↑↓ 改高亮(边界停住);Enter 执行无参命令并清空输入;Tab 同 Enter。
  - `/model` Enter → 输入变 `"/model "` 进参数模式、面板列建议;选建议 → 调 `patchAgent`(mock)。
  - Esc 关面板后 Enter → 走 `onSend`(直通)。
  - 各命令派发到正确动作(mock api/store):`/compact`→compactSession、`/new`→createSession+setSession、`/memory`→openSettings("memory")。

---

## 文件清单

**新增**
- `frontend/src/components/slash/commands.ts`
- `frontend/src/components/slash/useSlashCommands.ts`
- `frontend/src/components/slash/SlashPalette.tsx`
- `frontend/src/components/slash/StatusCard.tsx`
- `frontend/src/components/slash/commands.test.ts`

**修改**
- `frontend/src/components/Composer.tsx`(接面板状态机 + 键盘路由 + 渲染)
- `frontend/src/components/Composer.test.tsx`(扩展用例)
- `frontend/src/api/client.ts`(`compactSession`)
- `services/backend/src/agent_cloud_backend/api/sessions.py`(`POST /{id}/compact`)
- `services/backend/tests/`(新增 compact 端点测试文件)
