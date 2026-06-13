# 定时任务(Scheduled Tasks)设计

> 状态:已与用户确认(2026-06-13),待用户复核本 spec 后进入实现 plan。
> 范围:为 agent-cloud 增加"定时任务"——用户/agent 可排一个提示词,按 once/interval/cron 周期自动跑一回合,结果落成侧栏可见的新会话。

## 1. 目标

让用户(经 UI)或 agent(经工具)创建定时任务:到点自动以指定 agent 跑一回合预设提示词,产物作为**新会话**落地、侧栏可见;并让发起者**知道它跑没跑、成没成**。

非目标(v1 不做,见 §11):webhook 投递、错峰 stagger、运行次数上限、"任务常驻单会话"模式、LLM 推断式 commitments、独立运行历史表。

## 2. 参考实现速记

- **hermes-agent(`cron/`)**:单用户、`jobs.json` 文件存储。三态排期 `once`/`interval`/`cron`(croniter)。**at-most-once**:`advance_next_run()` 在 `run_job()` 之前推进。**错过补偿**:陈旧超过 grace 的周期任务快进、不补积压。执行错误 `last_error` 与投递错误 `last_delivery_error` 分列;周期任务绝不静默禁用。`[SILENT]` 抑制投递、仍存档。cron 上下文强制禁用 `cronjob` 工具(防自我繁殖)+ 组装后 prompt 注入扫描。
- **openclaw(`cron/`)**:多租户(`store_key`)、SQLite。`cron_jobs` 表 + 独立 `cron_run_logs`。**部分索引** `(store_key, enabled, next_run_at_ms) WHERE next_run_at_ms IS NOT NULL`。三态 `at`/`every`/`cron`。会话目标 `main`/`isolated`/`current`/`session:ID`;投递 `none`/`announce`/`webhook`(SSRF 防护)。执行状态与投递状态分列。armed timer + 重启 catch-up + stagger 防惊群。另有 `commitments`(LLM 推断式跟进)——超出本特性。

两者收敛出的标准做法,本设计全部采纳:一行一任务(规格+状态分列)→ 索引找到期 → **先推进 next_run 再执行**(at-most-once)→ 快进错过的运行 → **复用普通回合执行路径 + 注入预设提示** → 投递到目标 + 执行/投递错误分列 + 周期任务不静默禁用。

## 3. 决策记录(用户拍板)

| 维度 | 决定 |
|---|---|
| 产物落地 | **每次触发新建一个会话**(标题带任务名+时间、带"定时"标记) |
| 完成通知 | 未读角标 + 管理面板(权威入口);**agent 排的期额外向"发起会话"回执**一条轻量系统消息 |
| 创建面 | **UI 管理面板 + agent 工具都做**;入口按钮并入 TopBar「工具/技能」那一排 |
| 排期类型 | **once + interval + cron 全套**(croniter) |
| 执行架构 | **backend `lifespan` 进程内 asyncio 轮询器**(否决独立 scheduler 容器 / OS cron) |
| 轮询周期 | 默认 **30s**(可配) |
| `[SILENT]` | 保留会话作审计,仅**抑制未读角标**、任务状态记 `skipped`(v1 不删会话) |

## 4. 关键架构发现(决定实现形状)

1. **`lifespan` 已有后台任务范式**:`main.py` 用 `asyncio.create_task(_reaper_loop(...))` 起回收循环,关停时 cancel + 等收尾。轮询器照此再起一个独立任务。
2. **无头回合路径现成**:非流式 `api/turn.py` 的 `run_turn_endpoint` 做的是 `try_acquire 锁 → 落用户消息 → build_run_turn_request → run_turn_via_worker(带重试/压缩) → 落 new_messages → maybe_compact → 释放锁`。把这段核心抽成 `execute_turn_headless(...)`,端点与轮询器共用。
3. **agent 工具落 backend DB 有现成先例 —— `remember` 工具**(关键):
   - worker `RememberingExecutor`(`remember.py`)只校验参数、返回合成确认 `ToolResult`,**完全不碰 DB / 不转沙箱**;
   - 该 tool_call + tool_result 随 `new_messages` 回到 backend;
   - backend `turn/runner.py:_persist`(line 66)调 `apply_remember_calls(session_id, new_messages)`:按 `call_id` 配对"非错误结果"的已接受调用、**服务端重校验 `enabled_tools`**、独立 best-effort 事务落库。
   - ⇒ `schedule_task` 工具照抄此模式,**不需要任何 worker→backend 反向通道**(worker 至今对 backend 零知识,刻意单向)。
   - **已知缺口**:`apply_remember_calls` 只接在流式 `_persist`,非流式 `api/turn.py:163` 落库路径没接。`schedule_task` 要两条路径都生效 → 把"落库 + 后处理"抽成共享函数,顺手补上 remember 的非流式缺口。
4. **会话归属**:`SessionRepository.create_for(user_id, agent_config_id, title)` 建会话;`Session` 有 `status`(idle/running)、`last_active_at`、锁原语(`try_acquire`/`heartbeat`/`release`)。会话当前列表序 `order_by(created_at, id)`。

## 5. 数据模型

### 5.1 新表 `scheduled_tasks`

规格列与状态列分开(便于排期逻辑只读规格、运行只写状态):

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid FK→users **ON DELETE CASCADE**, index | 归属用户 |
| `agent_config_id` | uuid FK→agent_configs **ON DELETE CASCADE** | 用哪个 agent 跑 |
| `name` | text NOT NULL | 面板展示 + 结果会话标题 |
| `prompt` | text NOT NULL | 每次注入的预设提示 |
| `schedule_kind` | text NOT NULL | `once` / `interval` / `cron` |
| `schedule_expr` | text NOT NULL | once=ISO8601(UTC);interval=整数秒;cron=5 段表达式 |
| `schedule_tz` | text NOT NULL default `'Asia/Shanghai'` | 仅 cron 用(croniter 时区);once/interval 忽略 |
| `enabled` | bool NOT NULL default true | 暂停=false |
| `next_run_at` | timestamptz NULL | 下次应跑时刻(UTC);NULL=不再跑(once 跑完/算不出) |
| `running_since` | timestamptz NULL | 本次执行开始时刻(并发护栏,见 §6);完成清空 |
| `last_run_at` | timestamptz NULL | 上次实际跑的时刻 |
| `last_status` | text NULL | `ok` / `error` / `skipped` |
| `last_error` | text NULL | **执行**错误(回合抛错/worker 错) |
| `last_delivery_error` | text NULL | **投递**错误(建会话/回执失败)——与上分列 |
| `last_run_session_id` | uuid FK→sessions **ON DELETE SET NULL** NULL | 最近一次结果会话(面板"查看") |
| `origin_session_id` | uuid FK→sessions **ON DELETE SET NULL** NULL | agent 在哪次会话里排的;UI 创建为 NULL(用于回执) |
| `created_at` / `updated_at` | timestamptz | TimestampMixin |

**索引**:`ix_scheduled_tasks_due` on `(enabled, next_run_at)` `WHERE next_run_at IS NOT NULL`(到期扫描);`ix_scheduled_tasks_user` on `(user_id)`。

### 5.2 `sessions` 表新增 2 列(最小侵入)

- `scheduled_task_id` uuid FK→scheduled_tasks **ON DELETE SET NULL** NULL —— 标记"这是某定时任务的一次运行";`WHERE scheduled_task_id = X` 即该任务全部运行(**无需单独 runs 历史表**)。
- `unread` bool NOT NULL default false —— 仅定时运行产出的会话置 true;侧栏角标专指"定时任务出了新结果你还没看"。

### 5.3 迁移

新增一支 Alembic 迁移:`down_revision` = 当前 head;`upgrade()` 建 `scheduled_tasks` + 两个索引,并 `op.add_column('sessions', scheduled_task_id)` / `unread`;`downgrade()` 反向。`scheduled_tasks.last_run_session_id` 与 `sessions.scheduled_task_id` 互为可空 FK,建表顺序:先建 `scheduled_tasks`(此时 `last_run_session_id` 的 FK 指向已存在的 `sessions`),再 alter `sessions` 加列。

## 6. 调度器(`lifespan` 轮询器)

新模块 `scheduler/poller.py`,在 `main.py:lifespan` 里 `asyncio.create_task(scheduler_loop(settings))` 起一个**独立**任务(不并进 `_reaper_loop`,周期不同),关停时同样 cancel + 等收尾。

每轮(默认每 `scheduler_poll_interval_seconds`=30s):

```sql
-- 在一个事务里取到期任务并加行锁,多副本各取各的
SELECT * FROM scheduled_tasks
WHERE enabled
  AND next_run_at IS NOT NULL
  AND next_run_at <= now()
  AND (running_since IS NULL OR running_since < now() - INTERVAL '<run_lease>')
ORDER BY next_run_at
LIMIT <batch_size>          -- 默认 10
FOR UPDATE SKIP LOCKED;     -- 多副本安全:别的副本锁住的行直接跳过
```

对取到的**每个**任务,在**同一加锁事务**内先决定下一步并落"规格/状态前移",**再提交释放行锁**,**然后才执行回合**(回合很慢,绝不持有 `scheduled_tasks` 行锁):

1. 用 `scheduler/schedule.py:compute_next_run(kind, expr, tz, *, from_time=now)` 算 `new_next_run_at`:
   - `once` → `NULL`,同时 `enabled=false`(跑完即停)。
   - `interval` → 以"原排期相位"前移:`n = ceil((now - next_run_at) / interval)`,`new_next = next_run_at + max(1, n) * interval`(即至少前移一个周期,且跳过已错过的整数个周期 → 不补积压)。
   - `cron` → `croniter(expr, now, tz).get_next(datetime)`。
2. **错过补偿(仅周期任务)**:若 `next_run_at < now - grace`(grace = `clamp(period/2, 120s, 2h)`;cron 的 period 取"当前与下次的间隔"近似),则判为**陈旧**:写 `new_next_run_at`、`last_status='skipped'`、`last_run_at=now`,**本轮不执行**(避免停机后惊群补跑)。`once` 任务不快进——用户要的就是那一次,迟到也跑。
3. 否则判为**到期**:置 `running_since=now`、写 `new_next_run_at`(及 once 的 `enabled=false`),**提交**(释放行锁)。
4. 提交后,在轮询器任务里(非阻塞地)`await run_scheduled_task(task_snapshot)` 执行回合(见 §7)。可并发执行多个到期任务(有上限);单个失败不影响其它,也不退出循环。

`run_lease`(默认 15 min):`running_since` 超过它即视为"上次执行崩溃残留",允许重新拾取——与会话锁的租约思路一致。正常完成会清空 `running_since`。

配置(`config.py` 新增,均可 env 覆盖):`scheduler_enabled`(default true)、`scheduler_poll_interval_seconds`(30)、`scheduler_batch_size`(10)、`scheduler_run_lease_seconds`(900)、`scheduler_max_concurrent_runs`(默认 4)。

## 7. 执行器(复用无头回合)

把 `api/turn.py` 非流式回合核心抽成 `turn/headless.py:execute_turn_headless(session_id, user_content, *, is_scheduled_run=False)`,端点与轮询器共用(端点变薄包一层)。它需要自取依赖(轮询器无 FastAPI `Depends`):`get_sessionmaker()`、`get_settings()`、`get_sandbox_manager()`、对象存储——与流式 GET/SSE 路径自建会话同款。

`run_scheduled_task(task)` 步骤:

1. 建会话:`create_for(user_id, agent_config_id, title="📅 {name} · {本地时间}")`,置 `scheduled_task_id=task.id`、`unread=true`,commit;记 `session_id`。
2. 组装运行消息:`user_content = CRON_HINT + "\n\n" + task.prompt`。
   `CRON_HINT` ≈ "[你正作为定时任务运行。产出你的报告/结果作为最终回复即可,系统会自动呈现;**不要**自己尝试投递。若确实没有新内容可报,**只**回复 `[SILENT]`(别的都不写)。]"
3. `execute_turn_headless(session_id, user_content, is_scheduled_run=True)`:内部 `try_acquire`(新会话必成功)→ 落用户消息 → `build_run_turn_request`(带 `is_scheduled_run=True`,见 §9 自排期护栏)→ `run_turn_via_worker` → 落 `new_messages` → `maybe_compact` → 释放锁。
4. 读最终 assistant 文本:
   - 以 `[SILENT]` 开头 → `last_status='skipped'`、`session.unread=false`(不打扰);保留会话(前端把 `[SILENT]` 渲染成"本次无新内容"灰条)。
   - 否则 → `last_status='ok'`。
5. 回写任务行:`last_run_at`、`last_status`、`last_error=NULL`、`last_run_session_id=session_id`、`running_since=NULL`。
6. **回执**(仅 `origin_session_id` 非空,即 agent 排的期、且非 `[SILENT]`):向 `origin_session_id` best-effort 追加一条 `role=system` 消息:"📅 定时任务「{name}」已运行 → 结果见新会话"(含结果会话 id 供前端链接)。追加用现有 `MessageRepository.append`(自动分配 seq);失败仅记 `last_delivery_error`,不影响主流程。

异常:回合抛错 → `last_status='error'`、`last_error=str(exc)`、`running_since=NULL`;**周期任务保持 enabled**(next_run 已前移,下周期再试);once 已 `enabled=false`。建会话/回执失败 → `last_delivery_error`。

## 8. 投递与通知

- **产物**:每次新建会话(§7)。
- **权威入口——管理面板**:TopBar「工具/技能」那排加一个「定时任务」按钮/弹层,列每个任务:`name`、下次运行、上次运行+状态(✅/⚠️/⏭skipped)、`查看最新结果`(跳 `last_run_session_id`)、暂停/恢复、编辑、删除、`立即运行`。
- **侧栏**:`scheduled_task_id != null` 的会话显示"定时"小标;`unread` 显示未读圆点。打开会话即清未读(见 §10 `mark-read`)。结果会话需被侧栏**呈现到显眼处**(按 recency 排序 / 置顶逻辑由前端任务定;权威性仍由面板兜底)。
- **回执**:见 §7.6。

## 9. 创建面

### 9.1 UI(REST CRUD)

新路由 `api/scheduled_tasks.py`(挂进 `main.py`),全部按 `current_user` 归属:
- `GET /scheduled-tasks` —— 列出本人任务(含状态摘要)。
- `POST /scheduled-tasks` —— 建:`{name, prompt, agent_config_id, schedule_kind, schedule_expr, schedule_tz?}`。服务端校验(见 §9.3)并算初始 `next_run_at`。
- `PATCH /scheduled-tasks/{id}` —— 改任意字段;`enabled` 切换即暂停/恢复。恢复或改排期时重算 `next_run_at`(周期=下个未来时刻;once=原时刻,若已过则置 `now()` 尽快补跑)。
- `DELETE /scheduled-tasks/{id}`。
- `POST /scheduled-tasks/{id}/run-now` —— 置 `next_run_at=now()`,由轮询器在 ≤1 个周期内拾取(**单一执行路径**,不另开旁路)。
所有写操作校验 `agent_config_id` 属于本人。

### 9.2 agent 工具 `schedule_task`(remember 模式)

- worker 新增 `schedule_task.py`:`SCHEDULE_TASK_SPEC`(参数 `name`、`prompt`、`schedule_kind`、`schedule_expr`、可选 `schedule_tz`)+ `schedule_task_enabled(enabled_tools)` + `SchedulingExecutor(ToolExecutor)` 装饰器——校验参数、返回合成确认(如"已为你排期:{name},下次 {…}"),**不碰 DB、不转沙箱**。
- `server.py:_build_executor` 包一层:`executor = SchedulingExecutor(executor, enabled=schedule_task_enabled(enabled_tools) and not request.is_scheduled_run)`(自排期护栏见 §10)。
- backend 新 `turn/schedule_apply.py:apply_schedule_task_calls(session_id, new_messages)`:仿 `apply_remember_calls`——按 `call_id` 配对非错误结果的已接受 `schedule_task` 调用、**服务端重校验 `enabled_tools`**、解析+校验排期(§9.3)、以 `origin_session_id=session_id`、`user_id`/`agent_config_id` 取自该会话,INSERT `scheduled_tasks` 行并算 `next_run_at`;独立 best-effort 事务。
- **接线两条落库路径**:把 `runner.py:_persist` 里"落消息后的后处理"(现有 `apply_remember_calls` + 新 `apply_schedule_task_calls`)抽成 `persist_post_process(session_id, new_messages, enabled_tools)`,流式 `_persist` 与非流式 `api/turn.py` 落库后**都**调它(修掉 remember 的非流式缺口)。

### 9.3 排期校验 / 解析(`scheduler/schedule.py`)

- `validate_and_normalize(kind, expr, tz) -> (normalized_expr, error?)`:
  - `once`:解析 ISO8601 → 必须是**将来**时刻(允许 ≤ 容差的过去按 now);存 UTC ISO。
  - `interval`:正整数秒,且 **≥ 60s**(最小间隔护栏,防与 30s 轮询打架);友好串("30m"/"2h"/"1d")归一化为秒。
  - `cron`:`croniter.is_valid(expr)` 且 `tz` 可解析(`zoneinfo`)。
- `compute_next_run(kind, expr, tz, from_time)`:once→该时刻(过去则 now);interval→见 §6.1;cron→`croniter(...).get_next`。
- 新依赖:`croniter` 加入 `services/backend` 的 `pyproject.toml`(与 hermes 同库,Python 纯算)。

## 10. 错误与安全

- **执行 vs 投递错误分列**(§5.1 / §7)。
- **周期任务绝不静默禁用**:算不出 `next_run_at`(坏 cron 等)→ 保持 `enabled=true`、`next_run_at=NULL`、`last_status='error'`、`last_error` 写明,面板高亮"排期异常"。(hermes #16265 教训)
- **防自我繁殖**:`RunTurnRequest` 加 `bool is_scheduled_run`。worker 在该标记下**不暴露** `schedule_task`(§9.2);backend `apply_schedule_task_calls` 对 `session.scheduled_task_id IS NOT NULL` 的会话**跳过**落库(纵深防御)。⇒ 定时跑出来的 agent 不能再排新定时任务。(对应 hermes cron 上下文禁用 `cronjob` 工具)
- **服务端不信任 worker**:agent 排期的参数来自 LLM → `apply_schedule_task_calls` 重校验 `enabled_tools` + 排期合法性 + 归属(`user_id`/`agent_config_id` 取自服务端会话,不取 LLM 给的)。
- **未读清除**:新增 `POST /sessions/{id}/mark-read` 置 `unread=false`(GET 取消息不应有副作用 → 单独端点);前端打开会话时调。
- **多副本竞争**:`FOR UPDATE SKIP LOCKED` + advance-before-run + `running_since` 租约,保证同一到期任务不被两个副本/两轮重复触发。

## 11. 范围(YAGNI)

**v1 含**:`scheduled_tasks` 表 + `sessions` 两列 + 迁移;`lifespan` 轮询器(SKIP LOCKED / advance-before-run / 快进 / running 护栏);无头执行器复用 + 新会话投递 + `[SILENT]`;管理面板 + REST CRUD + run-now + mark-read;agent `schedule_task` 工具(remember 模式 + 两条落库路径);once/interval/cron(croniter);执行/投递错误分列;防自排期;回执。

**推迟**:webhook/外部投递、错峰 stagger、运行次数上限(repeat)、"任务常驻单会话累积"模式、LLM 推断式 commitments、独立运行历史表(复用按 `scheduled_task_id` 过滤会话)、子分钟级精度、跨任务依赖链(hermes `context_from`)、no-agent 纯脚本模式、pre-run 脚本/wake-gate。

## 12. 测试策略

- **schedule.py 单测**:`validate_and_normalize` 三态边界(过去 once、<60s interval、坏 cron、坏 tz);`compute_next_run` 三态 + interval 错过多个周期的快进 + cron 跨时区。
- **repository 单测(testcontainers PG)**:CRUD;到期查询 `FOR UPDATE SKIP LOCKED` 选行正确;`running_since` 租约过滤;advance-before-run 语义。
- **轮询器**:双并发轮询器对同一到期任务**不重复触发**(两个 sessionmaker 模拟两副本);陈旧周期任务快进+skipped 不执行;once 跑完 `enabled=false`。
- **执行器**:建会话→跑回合(mock worker / fake `run_turn_via_worker`)→落 `last_*` + `last_run_session_id`;`[SILENT]`→skipped + unread=false;执行抛错→error 且周期任务保持 enabled;回执写入 origin 会话。
- **agent 工具**:`SchedulingExecutor` 返回确认且不碰 DB;`apply_schedule_task_calls` 落库 + `enabled_tools` 守卫 + `is_scheduled_run` 跳过(仿 remember 既有测试);流式与非流式两路都触发后处理。
- **API**:CRUD 归属隔离(别人的任务 404/403);校验 422;run-now 置 next_run。
- **前端**:面板组件(列表/创建/暂停/删除/查看)+ 侧栏未读点/定时标 —— vitest;`npm run lint`(tsc -b)。
- 后端按既定:`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker"`。

## 13. 文件改动地图(供 writing-plans 切任务)

**backend**
- 新 `models/scheduled_task.py`;`models/session.py` 加 `scheduled_task_id`/`unread`
- 新 `repositories/scheduled_task.py`(CRUD + 到期查询 + advance);`repositories/session.py` 加 `set_unread`/`mark_read`/建会话时写 `scheduled_task_id`
- 新 `alembic/versions/xxxx_scheduled_tasks.py`
- 新 `scheduler/__init__.py`、`scheduler/schedule.py`、`scheduler/poller.py`
- 新 `turn/headless.py`(抽 `execute_turn_headless`);`api/turn.py` 改薄 + 接共享后处理
- 新 `turn/schedule_apply.py`;`turn/runner.py` 抽 `persist_post_process` 并在 `_persist` 调用
- 新 `api/scheduled_tasks.py`;`api/sessions.py`(或就近)加 `mark-read`
- `main.py`(起轮询器任务 + 注册路由);`config.py`(scheduler 配置项)
- `pyproject.toml` 加 `croniter`
- proto `worker.proto` 加 `bool is_scheduled_run`(重生成 stubs)

**worker**
- 新 `schedule_task.py`;`server.py:_build_executor` 包 `SchedulingExecutor`(gated by enabled & not is_scheduled_run);重生成 proto stubs

**frontend**
- api client `scheduledTasks` CRUD + `markRead`;store 状态;`ScheduledTasksPanel` + TopBar 按钮;Session 列表未读点/定时标;types(`ScheduledTask`、`Session.scheduled_task_id`/`unread`);打开会话调 mark-read

## 14. 实现分期(plan 建议顺序)

1. **数据层**:表 + 模型 + 迁移 + 仓库 + `schedule.py` + 单测。
2. **调度+执行**:`execute_turn_headless` 抽取 + 轮询器 + `run_scheduled_task` + 新会话投递 + `[SILENT]` + 配置 + `main.py` 接线 + 测试。
3. **UI 后端**:REST CRUD + run-now + mark-read + 测试。
4. **agent 工具**:proto `is_scheduled_run` + worker `SchedulingExecutor` + backend `apply_schedule_task_calls` + 共享后处理(补非流式缺口)+ 自排期护栏 + 测试。
5. **前端**:面板 + 按钮 + 未读/定时标 + 接线 + 测试 + preview 截图。
6. **收尾**:全量回归 + 对抗审查 + PR。
