# notify 工具(系统通知 + 网页弹窗)设计

> 状态:已与用户确认(2026-06-14),待复核本 spec 后进入实现 plan。
> 范围:给 agent 一个 `notify(title, body)` 工具,触发**OS 系统通知 + 应用内弹窗**。主用例:定时任务到点提醒用户;对话中也可即时提醒。

## 1. 目标

agent 调用 `notify(title, body)` → 用户在浏览器收到一条系统通知(OS 级,Web Notifications API)+ 应用内 toast 弹窗。对话中的 agent 与定时任务运行中的 agent 都能调用。

非目标(v1 不做,见 §10):Web Push(浏览器全关也能收)、通知历史中心、富媒体/按钮/分级通知。

## 2. 决策记录(用户拍板)

| 维度 | 决定 |
|---|---|
| 送达范围 | **仅"标签页开着时"**:Web Notifications API(OS 通知)+ 应用内 toast,前端**轮询**拉取(复用 sessions/skills 那套 react-query 轮询)。**不引 Web Push / service worker**。 |
| 触发场景 | **对话 + 定时任务都支持**;两处都是 agent **显式调用** `notify` 工具(非每次定时运行自动弹)。 |
| 送达机制 | **专表 `notifications` + 轮询**(否决"复用未读角标"/"SSE 双路")。 |
| 与未读机制 | **互补**:notify = 主动弹窗;未读角标/结果会话 = 被动留痕。并存,不合并。 |
| 权限 | `Notification.requestPermission()` 需用户手势 → 提供「开启系统提醒」按钮;**优雅降级**:应用内 toast 永远能弹,OS 通知是授权后的加成。 |

## 3. 复用的现成机制(降低实现成本)

- **agent 工具落 DB = remember 模式**(spec 2026-06-13-scheduled-tasks §3.3):worker 装饰器返回合成确认、不碰 DB;tool_call/result 随 `new_messages` 回 backend;落库后处理扫描并 INSERT。
- **统一后处理 `turn/post_persist.py:run_tool_side_effects(session_id, new_messages)`** 已存在(现调 `apply_remember_calls` + `apply_schedule_task_calls`),流式 `runner._persist` 与非流式 `execute_turn_headless` 两路共用。notify 只需再挂一个 `apply_notify_calls` 进去 —— **定时任务(无头路径)与对话(两路)自动全覆盖**。
- **前端 react-query 轮询范式**:`sessions`/`agents`/`skills` 都用 `useQuery` 拉取。notify 监听器照此加一个 `["notifications", userId]` 轮询。
- **enabled_tools 服务端重校验** + `BUILTIN_TOOLS` 工具开关(`agentConfig.ts`)。

## 4. 数据模型

新表 `notifications`:

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid FK→users **CASCADE**, index | 归属用户 |
| `title` | Text NOT NULL | 通知标题 |
| `body` | Text NOT NULL | 通知正文 |
| `origin_session_id` | uuid FK→sessions **SET NULL** NULL | 哪个会话触发(点通知可跳过去;定时任务则是结果会话) |
| `delivered_at` | timestamptz NULL | 已弹给前端的时刻;NULL=待送达 |
| `created_at` | timestamptz | TimestampMixin |

索引 `ix_notifications_undelivered`:`(user_id, created_at)` partial `WHERE delivered_at IS NULL`(前端只查未送达)。
Alembic 迁移:`down_revision` = 当前 head;`origin_session_id` FK 指向已存在的 `sessions`(无互引环,**无需 `use_alter`**)。

## 5. agent 工具 `notify`(remember 模式)

- **worker** 新 `notify.py`:`NOTIFY_SPEC`(参数 `title`、`body`,均必填)、`notify_enabled(enabled_tools)`、`NotifyingExecutor(ToolExecutor)` 装饰器——校验 title/body 非空,返回合成确认(如 `"已提醒:{title}"`),**不碰 DB、不转沙箱**。`server.py:_build_executor` 包一层:`executor = NotifyingExecutor(executor, enabled=notify_enabled(enabled_tools))`。
  **注意**:notify **不**像 `schedule_task` 那样按 `is_scheduled_run` 关闭——定时任务运行里调 notify 正是主用例,必须放行。
- **backend** 新 `turn/notify_apply.py`:`apply_notify_calls(session_id, new_messages) -> int`,仿 `apply_schedule_task_calls`——按 `call_id` 配对非错误结果的已接受 `notify` 调用、**服务端重校验 enabled_tools**、`user_id`/`origin_session_id` 取自服务端会话,INSERT `notifications` 行。独立 best-effort 事务。
- **接入** `turn/post_persist.py:run_tool_side_effects`:循环加上 `apply_notify_calls`(与 remember/schedule_task 并列,各自 best-effort)。
- **前端** `agentConfig.ts` `BUILTIN_TOOLS` 加 `{ name: "notify", desc: "提醒用户(系统通知 + 网页弹窗)" }`。

## 6. API

- `GET /notifications`:返回本人**未送达**(`delivered_at IS NULL`)通知,按 `created_at`。response_model `list[NotificationRead]`。
- `POST /notifications/mark-delivered`:body `{ "ids": [uuid, ...] }`,把这些(且属本人)置 `delivered_at=now()`。幂等。
- schemas `schemas/notification.py`:`NotificationRead`(`from_attributes=True`:id/title/body/origin_session_id/created_at)、`MarkDeliveredRequest`(ids)。
- 路由注册进 `main.py`。

## 7. 前端

- **全局监听器 `components/NotificationListener.tsx`**,挂在 `App`(始终在线,与当前选中会话无关):
  - `useQuery(["notifications", userId], () => api.listNotifications(), { enabled: !!userId, refetchInterval: 15000 })`。
  - 收到未送达通知 → 对每条:① 若 `Notification.permission === "granted"` 则 `new Notification(title, { body })`(OS 通知);② 入应用内 toast 队列;③ 收齐后 `POST mark-delivered(ids)` + 失效查询(避免下轮重弹)。
  - 渲染 **toast 栈**(新 `components/ui/Toast` 或内联):右下角可堆叠、可手动关、点击跳 `origin_session_id`(若有)。
  - **权限 banner**:当 `Notification.permission === "default"`(未决)时,渲染一条「开启系统提醒」小条 + 按钮;点击(用户手势)→ `Notification.requestPermission()`。granted/denied/用户关掉后不再显示(用 localStorage 记一次性关闭)。
- **优雅降级**:`window.Notification` 不存在 / 权限非 granted → 只弹应用内 toast(功能不残);只有 OS 通知缺失。
- **types**:`Notification`(前端 TS 接口:id/title/body/origin_session_id/created_at)。
- **api/client.ts**:`listNotifications()`、`markNotificationsDelivered(ids)`。

## 8. 数据流

- **对话中**:用户「提醒我 X」→ agent 调 `notify(title,body)` → tool result 进 `new_messages` → `run_tool_side_effects` → `apply_notify_calls` INSERT(`origin_session_id` = 当前会话)→ 前端轮询拾取(≤15s)→ OS 通知 + toast。
- **定时任务**:任务到点 → 无头回合里 agent(prompt 形如「提醒我 X」)调 `notify` → 同一落库后处理路径(headless 也走 `run_tool_side_effects`)→ INSERT(`origin_session_id` = 结果会话)→ 任一开着的标签页轮询拾取 → 弹窗。

## 9. 错误处理 / 边界

- `apply_notify_calls` best-effort、独立事务,绝不拖垮消息持久化(与 remember/schedule 同)。title/body 空则跳过该调用。
- 多标签页:每个标签页各自轮询 + 弹 + mark-delivered → 同一通知可能在多个标签页各弹一次(轻微重复);mark-delivered 幂等。v1 接受。
- 权限被拒 / 浏览器不支持 Notification → 仅 toast。
- 轮询仅在已登录(`userId`)时跑;退登停。

## 10. 范围(YAGNI)

**v1 含**:`notifications` 表 + 迁移;worker `notify` 工具 + `apply_notify_calls` + 接入 `run_tool_side_effects`;`GET /notifications` + mark-delivered;前端全局监听器 + OS 通知 + 应用内 toast + 权限按钮 + 优雅降级;`BUILTIN_TOOLS` 加 notify。
**推迟**:Web Push(浏览器全关送达)、通知历史中心/列表页、通知分级/图标/操作按钮、按 document.visibility 暂停轮询、跨标签页去重(BroadcastChannel/leader 选举)。

## 11. 测试

- **worker**:`notify_enabled`;`NotifyingExecutor` specs 受 enabled 门控、拦截 notify 返回确认且不转内层、非 notify 委托内层、title/body 空报错(仿 `test_schedule_task.py`)。
- **backend**:`apply_notify_calls` 落库 + enabled_tools 守卫 + 非错误结果配对 + user/origin 取自会话(仿 `test_schedule_apply.py`);`run_tool_side_effects` 仍各自 best-effort(notify 抛错不影响 remember/schedule);API CRUD 归属隔离 + mark-delivered 幂等;迁移建表 + 部分索引。
- **前端**:`NotificationListener` 轮询到通知 → 弹 toast + 调 `markNotificationsDelivered` + (mock `window.Notification` 已授权时)构造 Notification;权限 banner 在 `permission==="default"` 显示、点击调 `requestPermission`;降级(无 Notification/未授权)只弹 toast。vitest mock `window.Notification` + `api`。
- 后端 `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker"`;worker `uv run pytest`;前端 `npm run lint` + `npm test`。

## 12. 文件改动地图(供 writing-plans 切任务)

**backend**:`models/notification.py`(新)+ `models/__init__.py`;`alembic/versions/xxxx_notifications.py`(新);`repositories/notification.py`(新:list_undelivered / mark_delivered / get_owned);`turn/notify_apply.py`(新);`turn/post_persist.py`(挂 apply_notify_calls);`schemas/notification.py`(新);`api/notifications.py`(新)+ `main.py`(注册路由)。
**worker**:`notify.py`(新);`server.py`(`_build_executor` 包 `NotifyingExecutor`)。
**frontend**:`types.ts`(`Notification`);`api/client.ts`(list/markDelivered);`agentConfig.ts`(`BUILTIN_TOOLS` 加 notify);`components/NotificationListener.tsx`(新,挂进 `App.tsx`);toast UI(`components/ui/Toast.tsx` 或内联)。

## 13. 实现分期(plan 建议顺序)

1. **数据层**:表 + 模型 + 迁移 + 仓库。
2. **agent 工具 + 落库**:worker `notify` + server 接线;backend `apply_notify_calls` + 接入 `run_tool_side_effects`;`BUILTIN_TOOLS`。
3. **API**:schemas + `GET /notifications` + mark-delivered + 注册。
4. **前端**:types + client + `NotificationListener`(轮询 + OS 通知 + toast + 权限 banner + 降级)+ 挂进 App。
5. **收尾**:全量回归 + 对抗审查 + PR。
