# 无状态 Agent Cloud — 设计文档

- 日期:2026-06-05
- 状态:设计已与需求方逐节确认,待最终审阅
- 参考实现:openclaw(`/Users/wuhaowen/src/llm-agent/study/openclaw`)——作为**设计蓝本**,非代码来源

---

## 1. 背景与目标

**现状痛点**:现有产品基于 openclaw 做云端 agent 托管,**一个用户对应一个 openclaw 实例**。该实例把 agent 的"脑"、对话状态(本地 JSONL)、用户配置、实时连接(WS/MCP/channel/cron)、工作区文件**全部焊死在一个进程里**。任何一处崩溃即全部丢失,且无法横向扩容、资源被单用户独占——非常不稳定。

**目标**:把架构拆成**有状态后端 + 无状态 agent 服务**。

- 用户的配置和上下文保存在**后端服务**(持久化)。
- 后端服务按需请求**无状态 agent 服务**执行任务。
- 一个用户可对应**多个可替换的 agent 实例**;某些实例崩溃不影响整体。
- agent 仿照 openclaw 的设计(agent-loop、工具体系、provider 抽象、上下文文件体系),但做成**无状态**。

**核心洞察**:稳定性来自**"状态放在哪",而非"计算活多久"**。把状态(对话、配置、文件、连接)从计算单元里搬到持久层后,计算单元即可随意替换。

### 非目标(v1 明确不做)

- openclaw 的**可分支会话树**(`moveTo`/分支导航)——v1 只做线性历史。
- **语义/向量 memory 检索**(openclaw 的 qmd/embedding)——v1 只做读取+追加,但数据模型**预留** embedding 接口。
- **回合中途断点续跑**——v1 采用"尽力而为",崩溃即整轮重试。
- 消息队列分发 worker、多区域卷、WebSocket 实时 steering——均作为后续演进,接口预留。

---

## 2. 关键决策汇总

| 维度 | 决策 |
|---|---|
| 设计范围 | 完整双服务:无状态 agent 服务 + 后端服务(持久化/上下文/认证/编排) |
| 实现语言 | **Python**(openclaw 为设计蓝本,不复用其 TS 代码) |
| 工具范围 | 文件读写 + shell + 代码执行(需真实 POSIX 文件系统) |
| 文件模型 | **每用户一份持久文件系统**,独立于 agent;用户可随时上传/下载;agent 运行时挂载 |
| 并发模型 | 会话内串行(一会话同时一个活跃运行);用户可有多个会话并发 + 多套 agent 配置 |
| 容错语义 | **尽力而为**,无状态边界落在"每一轮";崩溃丢当前轮,用户重试 |
| 流式 | 需要完整流式 |
| 前端↔后端协议 | **SSE + REST**(发消息/取消/文件=REST,回合输出=SSE) |
| 内部协议 | 后端↔worker、worker↔sandbox 用 **gRPC** 流式 |
| 运行时拓扑 | **方案 1:每用户可暂停 sandbox**(挂用户卷,空闲暂停,TTL 回收),对象存储做备份/上传下载/快照 |
| 安全拆分 | **"脑"(worker)与"沙箱"(执行)分层**:worker 持 LLM Key 可信,沙箱无 Key 不可信 |
| 配置形态 | openclaw 式 markdown 文档(AGENTS/SOUL/IDENTITY/USER/TOOLS/…),非单个 system_prompt |
| Memory | 读取+追加;存为 DB 行(非 .md 文件);分用户级 + 每 agent 级;预留向量检索 |
| Skill | openclaw 式 `SKILL.md`;**用户级安装**(市场/上传 zip/卸载),**每 AgentConfig 选启用**;渐进式披露;文件物化进沙箱执行 |
| 依赖 | 富基础镜像 + 项目级依赖(卷)+ 用户级 hermetic 包前缀(卷)+ 内部包代理;自定义 per-user 镜像 post-v1 |
| 项目结构 | monorepo(uv workspace 多包)但**部署独立**:`services/{backend,worker,sandbox}` + `packages/common` + `protos` + `frontend` + `apps` + `deploy` |

---

## 3. 架构总览

自上而下分层(绿=无状态可弃,橙=有状态持久):

```
前端 / 客户端(聊天 UI + 文件管理)
   │  ① SSE + REST(公网)
后端服务(Python/FastAPI,服务无状态·多副本)
   │  认证 · 会话编排 · 流代理(SSE) · 文件 API · 沙箱生命周期管理
   │  ② gRPC server-streaming(内网)
Agent Worker 池("脑",无状态·池化,持有 LLM Key)
   │  openclaw 式 agent-loop · provider 抽象 · 工具决策
   │  ↔ LLM Providers(Anthropic / OpenAI / …)
   ─ ─ ─ ⚠ 信任边界:Key 不下沉沙箱 ─ ─ ─
   │  ③ gRPC / 最小 HTTP(内网)
用户 Sandbox(每用户·可暂停,只跑 shell/file 工具,无 Key/LLM/他人数据)
   │  挂载
用户持久卷(实时 POSIX FS)

持久层(用户数据):
  · Postgres:用户 / agent 配置 / 会话 / 消息(对话上下文) / context_documents / memory_entries
  · 对象存储 S3:文件持久备份 + 上传/下载通道 + 沙箱暂停快照/冷启恢复
  · Secrets/KMS:provider API Key(worker 用,绝不下沉沙箱)
```

**有状态 vs 无状态**:

- **无状态/可弃**:后端服务进程(多副本)、agent worker(池化)、sandbox(每用户但仅挂载持久卷,无独有状态)。
- **有状态/持久**:Postgres、对象存储、用户持久卷、KMS。

### 3.1 项目结构(monorepo)与部署独立性

一个仓库(monorepo,便于共享历史与跨服务原子改动),但**部署单元彼此独立**(monorepo ≠ monolith):web / 后端 / worker / sandbox 各自构建独立镜像,可部署到**不同集群 / 区域 / 平台**。

```
agent-cloud/
├── pyproject.toml            # uv workspace 根(声明 members、统一 dev/lint)
├── protos/                   # 跨服务契约源(gRPC/protobuf):run_turn、exec_tool、流事件
├── packages/common/          # 共享 Python 库:契约类型 + proto 生成桩 + 纯 domain 类型
├── services/
│   ├── backend/              # FastAPI 后端 + 数据层 + 迁移(唯一访问 Postgres 者)
│   ├── worker/               # agent "脑"(agent-loop / provider / 工具决策)
│   └── sandbox/              # 沙箱运行时(exec_tool server)
├── frontend/                 # Web UI(TS/React,独立工具链)
├── apps/                     # 未来原生 app(ios/android/desktop)占位
├── deploy/                   # 各服务 Dockerfile + docker-compose + k8s
└── docs/                     # specs / plans
```

保证"各部署各的"的机制:

1. **每服务一个独立镜像**(`deploy/<svc>.Dockerfile`)→ 后端多副本、worker 池化、sandbox microVM 宿主、前端 CDN,各去各处。
2. **边界是网络契约,非进程内调用**:跨服务只走 `protos/` 的 gRPC(后端↔worker↔sandbox)与后端的 SSE/REST(前端↔后端)。
3. **`packages/common` 仅契约/纯类型**,构建时 vendor 进各镜像并**按版本钉死** + 契约向后兼容 → 各服务独立升级,不强迫同时重部署。
4. **跨服务地址 = 配置**(env / 服务发现):不同环境填不同 endpoint,代码不变。
5. **独立 CI/CD**:每个 `services/*` 独立构建 / 发布 / 回滚。
6. **DB 归后端独有**:仅 `services/backend` 访问 Postgres;worker 经 `run_turn` 拿数据、结果回传后端落库,memory 也经后端写。

---

## 4. 组件职责

### 4.1 后端服务(Python / FastAPI)

- **认证**:用户身份、会话归属校验。
- **会话编排**:接收用户消息,加会话锁(串行),组装上下文,选 worker,代理流,落库结果。
- **流代理**:把 worker 的 gRPC 事件流转成对前端的 SSE。worker 崩溃时向前端发 `error`,前端连接不断。
- **文件 API**:用户上传/下载/浏览自己的文件(直接读写其持久卷/对象存储,**无需 agent 在跑**)。
- **沙箱生命周期管理**:维护 SandboxRegistry、健康检查、spawn/pause/resume/recycle、预热池。
- 服务本身无状态,水平扩容,所有状态在 Postgres/对象存储。

### 4.2 Agent Worker 池("脑")

- 无状态、池化;任意 worker 处理任意用户、任意回合。
- 运行 openclaw 式 **agent-loop**:调 LLM(流式)、决策工具调用、组装消息、判断终止。
- **provider 抽象**:统一封装 Anthropic/OpenAI 等(参考 openclaw 的 StreamFunction 契约)。
- **持有 LLM Key**(从 KMS 取),属于可信区。工具执行通过 gRPC 下发给沙箱,**Key 绝不传入沙箱**。

### 4.3 用户 Sandbox(执行环境)

- 每用户一个、可暂停;只负责执行被下发的 shell/file 工具。
- 挂载该用户的持久卷;同用户多会话在此并发,各用各的 `work_subdir`。
- 不可信区:**无 Key、无 LLM 访问、无他人数据**;只暴露 `exec_tool` 一个 RPC 面。
- 强隔离(见 §11)。

### 4.4 持久层

- **Postgres**:关系数据(见 §5)。
- **对象存储 S3**:每用户前缀;文件备份、上传/下载、沙箱快照。
- **用户持久卷**:实时 POSIX FS,挂入沙箱。
- **Secrets/KMS**:加密的 provider Key。

---

## 5. 数据模型

> 配置类逻辑上是 markdown 文档,**物理上是 DB 行**(content 为 markdown 文本列),不落地为文件。

### 5.1 实体

**User** `(id, email, created_at)`

**AgentConfig**(每用户多套)`(id, user_id, name, model, provider, thinking_level, enabled_tools, permissions, key_ref→KMS, created_at, updated_at)`

**Session**(会话线程,可并发)`(id, user_id, agent_config_id, title, status[idle|running], work_subdir, created_at, last_active_at)`
- `status` 充当会话内串行锁:已 running 时拒绝同会话新回合。
- `work_subdir`:在用户同一份 FS 下,默认每会话一个子目录。

**Message**(隶属会话,有序追加)`(id, session_id, seq, role[user|assistant|tool], content[文本/工具调用/结果/思考], model, tokens, created_at)`
- v1 线性历史;长会话用 compaction 摘要压缩(写入特殊 message 或 session 字段)。

**context_documents**(配置文档)`(id, scope[user|agent], type[USER|AGENTS|SOUL|IDENTITY|TOOLS|HEARTBEAT|BOOTSTRAP], owner_id, content[markdown 文本], updated_at)`

**memory_entries**(追加型)`(id, scope[user|agent], owner_id, content, source_session_id, created_at, embedding[v1 NULL,预留])`
- 追加 = INSERT;读取 = SELECT(v1 全量/近期,后续换向量 top-k,结构不变)。

**skills**(用户级安装)`(id, user_id, name, description, source[bundled|registry|uploaded], version, requires, package_ref→对象存储, created_at)`
- skill 包文件(SKILL.md + 脚本/资源)存对象存储:`s3://.../users/{user_id}/skills/{name}/`。详见 §12。

**agent_skill_enables**(多对多:每 agent 选启用)`(agent_config_id, skill_id, enabled)`

**SandboxRegistry**(运营态,可放 Redis)`(sandbox_id, user_id, status[provisioning|active|paused|dead], endpoint, last_heartbeat, volume_handle)`
- 丢失即当死、重建。

**ProviderKeys**(KMS)`(key_ref, provider, ciphertext)`——worker 用,绝不下沉沙箱。

**UserVolume / ObjectStore**:`user_id → 卷句柄/挂载点`;`s3://bucket/users/{user_id}/...`。

### 5.2 配置 & Memory 的 scope

- **用户级**(每用户一份,所有 agent 共享):`USER.md`、用户 memory。
- **Agent 级**(每套 AgentConfig 一份):`AGENTS.md`、`SOUL.md`、`IDENTITY.md`、`TOOLS.md`、`HEARTBEAT.md`、`BOOTSTRAP.md`、agent memory。

### 5.3 组装与持久化

- **读(回合开始)**:worker `SELECT` 用户级文档 + agent 级文档 + 相关 memory + 对话历史 → 拼成分层 markdown context 注入 LLM。不落地成文件。
- **写 memory**:agent 调 `memory_append` 工具 → 后端 `INSERT` 一行(追加不覆盖)。
- **写消息**:回合成功完成时由后端落库(见 §8 持久化时机)。

---

## 6. 通信与协议

前端**只**与后端交互,绝不直连 worker/sandbox。三跳:

| 跳 | 链路 | 网络 | 协议 |
|---|---|---|---|
| ① | 前端 ↔ 后端 | 公网 | **SSE + REST**(发消息/取消/文件=REST,回合输出=SSE 流) |
| ② | 后端 ↔ Worker | 内网 | **gRPC server-streaming**(run_turn → 事件流;HTTP/2、protobuf、背压) |
| ③ | Worker ↔ Sandbox | 内网·信任边界 | **gRPC / 最小 HTTP**,stdout 流式;仅暴露 `exec_tool` |

- 第①跳选 SSE 而非 WebSocket:简单、穿透 CDN/代理、自动重连、无长连接粘性、扩展友好。取消用 `POST /cancel`。若未来需要"回合进行中的实时 steering",流层做成可替换抽象,再换 WebSocket,不影响上层。
- 第②跳 v1 直连 gRPC + LB/服务发现;扩展期可改"消息队列分发 + pub/sub 回流"。

---

## 7. 契约(Schema)

**① `run_turn`(后端 → Worker)**
```jsonc
{
  "session_id": "...", "user_id": "...",
  "agent": { "model": "...", "provider": "...", "thinking_level": "...",
             "enabled_tools": ["..."], "key_ref": "..." },
  "context": {
    "documents": [{ "scope": "user|agent", "type": "USER|AGENTS|...", "content": "..." }],
    "memory":    [{ "scope": "user|agent", "content": "..." }],
    "skills":    [{ "name": "...", "description": "...", "location": "/skills/<name>/SKILL.md" }],
    "messages":  [{ "role": "user|assistant|tool", "content": "..." }]
  },
  "user_message": { "content": "..." },
  "sandbox": { "endpoint": "...", "work_subdir": "..." },
  "stream":  { "channel_id": "..." }
}
```

**② 流式事件(Worker → 后端 → 前端,判别联合)**
```jsonc
{ "type": "text_delta", "text": "..." }
{ "type": "thinking_delta", "text": "..." }
{ "type": "tool_call_start", "call_id": "...", "tool": "...", "args": {} }
{ "type": "tool_progress", "call_id": "...", "chunk": "..." }   // 如 shell stdout 实时流
{ "type": "tool_result", "call_id": "...", "result": {}, "is_error": false }
{ "type": "turn_done", "usage": {}, "message_ids": ["..."] }
{ "type": "error", "message": "...", "recoverable": true }
```

**③ 工具执行 RPC(Worker ↔ Sandbox,信任边界)**
```
exec_tool(call_id, tool_name, args, work_subdir) -> stream<tool_progress> + tool_result
```
沙箱只拿到 工具名 + 参数 + 工作目录;无 Key、无 LLM、无他人数据。

**④ 回合完成(Worker → 后端)**
```jsonc
{ "new_messages": [ /* assistant + tool 消息 */ ],
  "usage": { "input_tokens": 0, "output_tokens": 0 } }
```

---

## 8. 回合生命周期

**准备**
1. 前端→后端:用户在 session S 发消息。后端**立即持久化这条 user 消息**。
2. 后端:加会话锁(`status=running`,已运行则拒绝);从 DB 载入 配置文档 + memory + 已启用 skill 元数据 + 历史。
3. 后端:确保用户 sandbox 在线(暂停则恢复 / 无则起),挂载用户卷,物化已启用 skill 到 `/skills/`。
4. 后端→worker:从池选空闲 worker,发 `run_turn`。

**agent 循环(流式)**
5. worker→LLM:流式请求(系统上下文 + 历史 + 工具定义)。
6. LLM→worker:流式 deltas(text/thinking/tool_call)。
7. worker→后端→前端:实时转发流事件。
8. 有工具调用 → worker→sandbox RPC 执行 @ `work_subdir`(⚠ 不传 Key)。
9. sandbox→worker→前端:工具结果(stdout 可再流式)。
10. worker:追加结果到 messages → 回到 5,直到 LLM 不再调用工具。
   - `memory_append` 工具 → 后端 `INSERT` 一行 memory。

**收尾**
11. worker→后端:`turn_done`(新 assistant/tool 消息 + 用量)。
12. 后端:持久化新消息;释放会话锁(idle);**异步**快照用户卷 → 对象存储。
13. 后端→前端:`turn_done`,前端结束本回合。
14. 空闲超 TTL:暂停/快照 sandbox,释放计算。

**持久化时机**:user 消息进来即落库;assistant/tool 消息**仅在第 12 步成功后**落库——失败不留半成品。

**并发**:同用户多 session → 多 worker 同时 RPC 进**同一沙箱**,各用各的 `work_subdir`;同 session 并发被会话锁拒绝。

---

## 9. 沙箱生命周期与运营

**状态机**:
```
无 ──首个回合(从预热池取)──▶ 预热分配(挂用户卷) ──▶ 活跃(服务回合)
活跃 ──空闲超 TTL──▶ 暂停(卸卷/释放计算) ──新回合──▶ 恢复 ──▶ 活跃
活跃/暂停 ──崩溃/健康失败──▶ 死亡 ──重建──▶ 预热分配
活跃 ──年龄/定期──▶ 回收(drain→kill,防 cruft 累积) ──下个回合──▶ 重建
```

- **预热池**:预先准备好通用沙箱,分配时只需挂用户卷 → 冷启动 ≈ "挂卷"而非"开机"。
- **暂停/恢复**:卷持久,暂停=卸卷+释放计算,恢复=取沙箱+挂卷;无需快照(若用本地盘则快照到 S3)。
- **用户卷载体(实现层)**:
  - 默认推荐:**durable 网络卷 / 每用户子目录**(如 EFS,跨 AZ 友好,仍每用户隔离)。
  - 可选:**块卷 + S3 快照**(本地盘更快,跨 AZ 靠快照恢复)。
- **skill 物化**:已启用 skill 从对象存储解包到沙箱 `/skills/<name>/`(只读层),缓存;install/uninstall 时失效,下回合重新物化。与用户工作文件分目录,互不混淆。

### 9.1 依赖管理(沙箱里跑脚本的依赖)

原则:**依赖也是状态 → 放持久层(用户卷 / 包前缀),沙箱保持临时**。与"文件/上下文放持久层、计算可弃"同构。分层:

1. **基础镜像(共享·无状态)**:富基础镜像预装常见 runtime(Python/Node/Go/…)+ 系统工具(git/curl/build/jq/ffmpeg/ripgrep/…)。版本化、集中更新,覆盖大多数需求,零成本秒级。
2. **项目级依赖(持久,在卷上)**:`venv` / `node_modules` / 项目本地包装在用户卷项目目录 → 与用户文件一起持久、跨实例自然存活(也是最佳实践)。
3. **用户级包前缀(持久,在卷上)**:"全局型"工具用 hermetic 包管理器(Nix / micromamba / conda)装到卷上的 prefix,持久且对基镜变化稳健(避免 ABI 失配)。
4. **Skill 依赖**:见 §12.5。
5. **(post-v1)自定义 per-user 镜像**:devcontainer 式自定义基镜,应对重系统依赖。

- **网络**:装包需出网,与 egress allowlist 冲突 → 走**内部包代理 / 镜像缓存**(PyPI/npm/…),沙箱只放行该代理;既限外泄又加速(缓存)。首次装慢,缓存在卷上后续快。
- **风险兜底**:卷上二进制可能因基镜升级失配 → 用 hermetic 包管理器 + 固定 per-user 基镜版本。
- **v1 范围**:富镜 + 项目级 + 用户级 hermetic 前缀 + 包代理;自定义镜像 post-v1。

---

## 10. 失败处理

| 组件挂 | 影响 | 存活 | 恢复 |
|---|---|---|---|
| 后端副本 | 该副本上的连接 | DB / 其他副本 / worker / sandbox | LB 换副本;前端 SSE 自动重连 |
| Worker | 当前这一轮 | 一切持久态 + 沙箱 + 用户卷 | 标失败 → 重试换 worker |
| Sandbox | 当前轮的工具执行 | 用户卷 / 历史 / 配置 / 连接 | 重建 + 重挂卷 → 重试 |
| 用户卷 | (持久存储层) | — | 存储层 HA + 对象存储快照恢复 |

**尽力而为**:计算层随便挂,持久层做 HA,最多丢"当前这一轮"。无半成品(assistant 消息仅成功后落库)。

---

## 11. 安全

- **信任边界(脑/沙箱拆分)**:LLM Key 与编排逻辑只在 worker;沙箱跑不可信 shell,被攻破/注入也偷不到 Key、连不到后端/他人数据。
- **沙箱隔离**:**microVM(Firecracker)/ gVisor 强隔离**,非裸容器。
- **出网策略**:egress allowlist,防注入后数据外泄;装包出网走**内部包代理/镜像缓存**(只放行代理),兼顾安全与加速(见 §9.1)。
- **资源限制**:cgroups 限 CPU/内存/磁盘,防噪声邻居与 OOM 拖垮宿主。
- **卷隔离**:每用户卷,沙箱只挂自己用户的子树,由沙箱管理器强制。
- **密钥**:KMS 加密,worker 运行时解密注入,绝不写入沙箱或日志。
- **Skill 供应链**:安装的 skill 会在沙箱里执行代码;沙箱隔离兜底执行风险,市场 skill 审核/签名,上传归档受 `allowUploadedArchives` 开关控制,每用户隔离使 skill 最多触及自身数据(详见 §12.5)。

---

## 12. Skill 系统

参考 openclaw 的 Agent Skills:一个 skill = 一个目录(`SKILL.md` + 脚本/资源),frontmatter 含 `name` / `description` / `requires`。采用**渐进式披露**——平时只注入元数据,用时才读全文。

### 12.1 Scope

- **安装在用户级**(用户的技能池):用户可自由安装 / 卸载。
- **每套 AgentConfig 选择启用哪些**(类似 `enabled_tools`);不同 agent 不同技能集,不必重复安装。

### 12.2 数据模型(见 §5)

- `skills`(用户级)+ `agent_skill_enables`(每 agent 启用映射);skill 包存对象存储 `s3://.../users/{user_id}/skills/{name}/`。

### 12.3 安装 / 卸载(后端 Skill API)

- `GET /skills`、`POST /skills/install`(市场/registry)、`POST /skills/upload`(zip 归档,受 `allowUploadedArchives` 开关)、`DELETE /skills/{id}`、`PUT /agents/{id}/skills`(启用/停用)。
- install:校验包 → 存对象存储 + 注册 Postgres → 失效该用户沙箱的 skill 缓存(下回合重新物化)。

### 12.4 回合时加载(渐进式披露,落进无状态模型)

1. 回合开始,后端确保该用户**已启用**的 skill 物化进沙箱:从对象存储解包到 `/skills/<name>/`(只读层;缓存,install/uninstall 时失效)。
2. worker 把已启用 skill 的 `<available_skills>`(仅 name + description + location)注入 prompt。
3. agent 判断相关 → 用 **read 工具读取沙箱里的 `SKILL.md`**(走 §7-③ 的 `exec_tool`)。
4. 按 SKILL.md 的命令在沙箱跑脚本。

> 因为 agent 是"读文件 + 跑脚本"来用 skill,skill 文件必须在沙箱——这与"工具在沙箱执行"完全一致,**不破坏无状态边界**。

### 12.5 依赖与安全

- **依赖**(`requires: bins`):v1 靠较全的沙箱基础镜像满足常见依赖;复杂/自定义依赖安装(brew/npm)作为后续。
- **供应链**:skill 在沙箱里跑代码 → 沙箱隔离(microVM/gVisor + egress allowlist)兜底执行风险;市场 skill 审核/签名,上传归档受开关控制;每用户隔离 → skill 最多触及该用户自身数据。

---

## 13. 测试策略

1. **单元(纯逻辑,假 LLM provider)**:agent-loop(工具分派/终止/错误分支,test-first)、上下文组装、provider 映射、契约序列化。
2. **工具**:shell/file/memory_append 对真实(本地)沙箱或临时目录;`exec_tool` RPC 契约。
3. **集成(不 mock 关键行为)**:BE↔Worker gRPC 流;沙箱 spawn/pause/resume/recycle;持久化落**真实 Postgres**(testcontainers);端到端 FE→SSE→工具→落库(假 LLM)。
4. **失败/韧性(重中之重,故障注入)**:杀 worker / 杀 sandbox 中途 → 标失败+无半成品+重试成功;同用户并发会话隔离;会话内串行锁;后端副本挂 SSE 重连。
5. **安全**:断言沙箱够不到 Key/后端/他人卷;egress 生效;注入无法越界偷 Key。
6. **流式/契约**:SSE 顺序/取消/重连;gRPC 背压。
7. **Skill**:安装/卸载/启用 API;skill 物化进沙箱 + 缓存失效;渐进式披露(元数据注入 + 按需读 SKILL.md);跑 skill 脚本端到端;上传归档开关与隔离。
8. **依赖**:项目级 venv/node_modules 跨回合持久;用户级 hermetic 前缀持久;包代理缓存命中;基镜升级后卷上 hermetic 包仍可用。

**原则**:假 LLM 保确定性零成本;DB 与沙箱用真实(其行为正是被验证对象,不 mock);故障注入是一等公民。

---

## 14. 后续演进(post-v1)

- memory 语义/向量检索(给 `memory_entries` 加 embedding 列 + ANN 索引)。
- 可分支会话树 + 更完善的 compaction。
- 回合中途断点续跑(细粒度 checkpoint + 工具幂等)。
- 第②跳改消息队列分发 + pub/sub,提升弹性。
- 第①跳按需引入 WebSocket(回合进行中实时 steering)。
- 用户卷多区域 / 跨 AZ 优化。
- skill 市场审核/签名 + 语义检索式 skill 发现。
- per-user 自定义沙箱镜像(devcontainer 式构建管线 + registry),应对重系统依赖。
```
