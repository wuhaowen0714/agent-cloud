# 压缩反馈修复 Implementation Plan

> **For agentic workers:** 纯前端;controller 直接 TDD 实现(子 agent 仅审查)。

**Goal:** 让 `/compact` 在发起压缩的那个会话里显示"正在压缩…"与结果,期间禁用该会话输入(消灭同会话 409),且反馈绝不串到别的会话;回合 409 文案友好化。

**Architecture:** 压缩状态从 Composer 本地 state 上移到 store,按 `sessionId` 存(与 `live` 单条、切会话即清不同——压缩状态须跨会话切换存活)。Composer 只渲染"当前会话"的压缩状态,天然隔离。

**Tech Stack:** React19 + zustand + vitest/RTL。

---

## 根因(已确认)

- `/compact` 在 [Composer.tsx](frontend/src/components/Composer.tsx) 经 `void cmd.run?.(ctx)` fire-and-forget,Composer 不跟踪进度;`disabled` 只绑回合流式,压缩期间输入框可用 → 用户发消息撞 `/turn/stream` 的 409(锁被压缩占用,[turn.py](services/backend/src/agent_cloud_backend/api/turn.py))。
- 反馈(`notify` flash)存 Composer 本地 state,跟"当前视图"走 → 在 A 压缩、切到 B,A 完成时 flash 弹到 B(串台)。
- 非锁卡死:`compact_session` finally 必释放 + 600s 租约兜底。

## Tasks

### CF-1 store per-session 压缩状态
- `types.ts`:`export type CompactResult = "compacted" | "nothing" | "busy" | "error"`(从 commands.ts 迁出,断 store↔commands 循环)。
- `store.ts`:`compactions: Record<string, CompactState>`;`CompactState = {phase:"running"} | {phase:"result"; result: CompactResult}`;actions `startCompaction(sid)` / `finishCompaction(sid,result)` / `clearCompaction(sid)`;`logout` 与切用户重置 `compactions:{}`;`setSession` **不**清(跨会话存活)。
- 测试 `store.test.ts`:set running→result→clear;切 session 不清 compactions;logout 清空。

### CF-2 compact 编排进 store
- `useSlashCommands.compact`:捕获 sid;`startCompaction(sid)` → try `compactSession(sid)` → `finishCompaction(sid, r.compacted?"compacted":"nothing")`,catch 409→"busy" 其余→"error"。返回 void。
- `commands.ts`:`compact.run` 简化为 `(c) => void c.compact()`;`SlashContext.compact: () => Promise<void>`;导出 `COMPACT_MESSAGES: Record<CompactResult,string>`。

### CF-3 Composer 只渲染当前会话压缩
- 读 `const sessionId = useStore(s=>s.sessionId)`、`compactions[sessionId]`。
- `running` → 顶部常驻 banner(spinner + "正在压缩上下文…",无关闭钮)+ `busy = disabled || compacting` 禁用 textarea/发送钮/斜杠面板/send 守卫。
- `result` → effect 弹 `COMPACT_MESSAGES[result]` flash(复用 notice,4s 自动消失)+ 立即 `clearCompaction(sid)`(flash 本地存活 4s)。
- 测试:running 时 banner + textbox disabled;A 压缩切到 B,B 不弹、输入可用;切回 A 弹结果;既有两条 same-session 结果用例仍绿。

### CF-4 回合 409 文案友好化
- `stream.ts` `streamTurn`:`res.status === 409` → `throw new Error("会话正忙(可能正在压缩上下文),请稍候重试")`(其余状态保持原样)。
- 测试:mock 409 fetch → done reject 带友好文案。

### CF-5 回归 + Fable 5 审查 + PR
- `npm run lint` + `npm test` 全绿;Fable 5 审竞态/跨会话/内存;修复后 PR,CI 绿合并。
