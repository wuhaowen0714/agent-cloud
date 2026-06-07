# 前端 Chat MVP 设计(spec)

> 状态:已与用户确认方向(2026-06-07)。范围=纯聊天闭环;栈=React+Vite+TS;连接=Vite 代理;风格=浅色 + teal 强调色。

## 1. 目标与范围

让用户在浏览器里**真正用起来核心回合**:建/选 user → 建/选 agent → 建 session → 发消息 →
看流式回答(文本 / 思考 / 工具调用)→ 看历史。先能用,再按真实反馈迭代。

**本版做(MVP):**
- user / agent / session 的建立与选择
- 聊天页:发送消息;`/turn/stream` 流式渲染(text_delta / thinking_delta / tool_call_start / tool_result / turn_done / error)
- 消息历史加载与展示
- 一键起全栈的开发脚本

**本版不做(留后续):** 文件上传/下载、skills 安装/启用 UI、agent 配置编辑、上下文文档/memory 编辑、登录鉴权、多用户切换 UI(MVP 用 localStorage 记住当前 user)。

## 2. 技术栈

- **React 18 + Vite + TypeScript**,独立项目位于 `frontend/`(自带 Node 工具链,不进 uv 工作区)。
- **TanStack Query** 管 REST 数据(users/agents/sessions/messages 的拉取+缓存+失效)。
- 轻量 **store**(Zustand)存「当前 user/agent/session id」+「进行中回合的流式状态」。
- **Tailwind CSS** 做样式(浅色主题 + teal 强调)。
- **Vitest + React Testing Library** 测试。

## 3. 连接后端

- 前端**只**连后端(REST + SSE),绝不直连 worker/sandbox。
- **Vite dev 代理**:`vite.config.ts` 把 `/api` 代理到 `http://localhost:8000`(可配),浏览器同源 → **后端无需 CORS**;代理透传 SSE。前端所有请求走 `/api/...`。
- **SSE**:`POST /api/sessions/{id}/turn/stream` 返回 `text/event-stream`。`EventSource` 只支持 GET,故用 `fetch` + `response.body.getReader()` 逐行解析 `data: {json}`。
- 生产部署(后续):前端构建为静态资源,由反代/静态托管 + 后端分开部署;本 spec 只覆盖开发联调。

### 用到的后端端点(均已存在,后端零改动)

| 用途 | 方法 + 路径 |
|---|---|
| 建 user | `POST /api/users` `{email}` |
| 取 user | `GET /api/users/{id}` |
| 列 agent | `GET /api/agent-configs?user_id=` |
| 建 agent | `POST /api/agent-configs` `{user_id,name,model,provider,...}` |
| 列 session | `GET /api/sessions?user_id=` |
| 建 session | `POST /api/sessions` `{user_id,agent_config_id,title?}` |
| 列消息 | `GET /api/sessions/{id}/messages` |
| 跑回合(流式) | `POST /api/sessions/{id}/turn/stream` `{content}` → SSE |

> 无「列 user」端点:MVP 用 localStorage 记住当前 user id(首次输邮箱建 user)。

## 4. 界面与交互

布局(单页):
- **左侧栏**:当前 user(邮箱,点可切换/新建);当前 agent 选择器(下拉选已有 / 新建);**会话列表**(按 user 列出,点切换;「+ 新会话」)。
- **主区(聊天)**:消息流 + 底部输入框(Composer)。

消息渲染:
- user 气泡:右侧,纯文本。
- assistant 气泡:左侧;**正文**由 `text_delta` 增量填充;**「思考」可折叠面板**由 `thinking_delta` 填充(默认折叠、弱化样式);**工具调用卡片**:工具名 + 参数(`tool_call_start`)→ 结果(`tool_result`,`is_error` 红色态)。
- 回合进行中:输入框禁用 + 显示「生成中…」;`turn_done` 后定稿、刷新历史;`error` 事件显示可重试提示(`recoverable`)。

首次流程:无 user → 输邮箱建 user(存 localStorage)→ 无 agent → 表单建 agent(name/model/provider,model 填你的端点模型名如 `DeepSeek-V4-pro`)→ 建 session → 聊天。

## 5. 设计系统(浅色 + teal)

- **基调**:干净的浅色「agent 控制台」。白/浅灰背景(`#fff` / `slate-50`),文字深 slate;**强调色 teal**(如 `teal-600`,hover `teal-700`),用于主按钮、选中态、流式光标。
- **排版**:正文 sans(系统 UI 字体栈);代码/工具参数 mono(`ui-monospace`)。层级用字号+字重+间距,不靠重色块。
- **留白**:充足 padding,卡片圆角 + 细边框(`slate-200`)+ 极淡阴影。
- **动效**:文本流式淡入 / 闪烁光标;思考面板展开/收起平滑;克制,不喧宾夺主。
- 深色主题:本版不做(可后续加)。

## 6. 组件(各司其职,可独立测)

- `src/api/client.ts` — typed REST 封装(基于 `/api` 的 fetch;返回类型)。
- `src/api/stream.ts` — `streamTurn(sessionId, content)`:fetch SSE → 异步产出 typed 事件(`TextDelta|ThinkingDelta|ToolCallStart|ToolResult|TurnDone|ErrorEvent`)。**纯函数式、可单测**(喂一段 SSE 文本断言事件序列)。
- `src/store.ts` — Zustand:当前 user/agent/session + 流式回合状态。
- 组件:`Sidebar`、`UserSwitcher`、`AgentSelector`、`SessionList`、`ChatView`、`MessageList`、`MessageBubble`、`ThinkingPanel`、`ToolCallCard`、`Composer`、`NewAgentForm`。
- `src/types.ts` — 与后端契约对应的 TS 类型(User/AgentConfig/Session/Message/SSE 事件)。

## 7. 数据流

- 进入页面:从 localStorage 取 user id → TanStack Query 拉 agents/sessions。
- 选/建 agent、建 session → 失效相关 query → 列表刷新。
- 发消息:乐观插入 user 气泡 → `streamTurn` 读 SSE → 把事件写入「进行中回合」store(assistant 正文/思考/工具卡逐步成形)→ `turn_done` 后失效 messages query 拉权威历史。
- 切 session:拉该 session 的 messages 渲染。

## 8. 开发跑起来

新增 **`scripts/dev_up.sh`**:
1. `docker run` 起 Postgres(若未运行)→ 等就绪。
2. `alembic upgrade head`(后端)建表。
3. 后台起 worker(`python -m agent_cloud_worker`,读仓库根 `.env` 的 OpenAI 凭据)。
4. 后台起 backend(`uvicorn agent_cloud_backend.main:app --port 8000`,`AGENT_CLOUD_*` 指向上面的 PG/worker)。
5. 起 frontend(`npm run dev`,Vite 5173)。
打印各端口 + 退出时清理。让用户 `bash scripts/dev_up.sh` 即可在浏览器用。

> 注:worker 读仓库根 `.env`(已支持);backend 也需相应 env(database_url / worker_endpoint / sandbox_base_root / object_store_root)。脚本里统一设置。

## 9. 测试

- `api/stream.ts` 解析器单测(Vitest):喂多段 `data:` 文本 → 断言产出的事件序列(含思考/工具/done/error/分片边界)。
- 关键组件测(RTL + mock):MessageBubble / ThinkingPanel / ToolCallCard 渲染;Composer 流式中禁用。
- e2e(Playwright)留后续。

## 10. 风险 / 取舍

- SSE 用 fetch 流式(非 EventSource),需手写分行解析 + 处理中断/取消(AbortController)。
- MVP 无鉴权,信任 localStorage 里的 user id(与后端 v1 无鉴权姿态一致)。
- 全栈联调需 Docker(Postgres);`dev_up.sh` 兜住。
- 深色主题 / 文件管理 / skills UI 等明确留后续。
