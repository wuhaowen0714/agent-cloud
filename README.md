# Agent Cloud

> 无状态、多租户的 **Agent Cloud**:用户创建可配置的 AI agent(模型 / Provider / 工具 / 技能),与之多轮对话;每个会话跑在**隔离沙箱**里,拥有持久工作区。后端是唯一访问数据库的服务,LLM 密钥只存在于 worker,沙箱按最小信任设计。

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white">
  <img alt="Vite" src="https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white">
  <img alt="gRPC" src="https://img.shields.io/badge/gRPC-contracts-244c5a?logo=grpc&logoColor=white">
  <img alt="Postgres" src="https://img.shields.io/badge/Postgres-16-4169E1?logo=postgresql&logoColor=white">
</p>

---

## 目录

- [它是什么](#它是什么)
- [核心特性](#核心特性)
- [架构](#架构)
- [信任与安全模型](#信任与安全模型)
- [技术栈](#技术栈)
- [仓库结构](#仓库结构)
- [快速开始](#快速开始)
- [配置](#配置)
- [开发](#开发)
- [工作原理](#工作原理)
- [路线图](#路线图)
- [许可证](#许可证)

---

## 它是什么

Agent Cloud 是一个把"可配置 AI agent + 隔离代码执行"做成多租户服务的平台。它适合用来:

- 给每个用户提供若干**自定义 agent**(不同模型、不同人设/指令、不同工具与技能);
- 让 agent 在**隔离沙箱**里真正执行命令、读写文件、编辑代码,工作区跨会话持久;
- 以**流式**(SSE)方式实时看到 agent 的思考、正文与工具调用;
- 用户**自带 LLM 密钥**(BYO-Key),密钥加密入库、按请求注入、绝不下发到前端或沙箱。

"无状态"指**业务进程(backend / worker / sandbox)本身不持有会话状态**:所有状态落在 Postgres 与持久工作区卷,进程可随时重启、横向扩展;会话锁用带租约的方式协调。

## 核心特性

- 🔐 **鉴权与多租户**:邮箱/密码注册登录;access JWT(内存) + httpOnly refresh cookie 静默续期;跨租户访问一律 404(不泄露存在性)。
- 🤖 **可配置 agent**:每个 agent 自带模型、Provider、思考档位、启用的工具、指令(`AGENTS` 文档)、绑定的凭据与技能。
- 🔑 **BYO-Key(自带密钥)**:每用户的 Provider 凭据用 **AES-256-GCM** 加密存储;回合时按请求把明文密钥注入 worker,**永不**进入沙箱、前端或日志。
- 💬 **流式对话**:基于 SSE 的回合事件(思考 / 正文 / 工具调用 / 工具结果);**断线可续看**(resume);瞬时错误**透明自动重试**;超窗自动**压缩历史**。
- 🛠️ **沙箱工具**:`bash`、`read_file`、`write_file`、`edit`(精确字符串替换,多段、保留 CRLF);全部在隔离沙箱内执行。
- 🧩 **技能(Skills)**:从 registry **安装**到用户对象库 → 在 agent 上**启用** → 每回合**物化**进沙箱并注入提示词;内置 `skill-creator`,支持**从工作区一键安装**自制技能。
- 📁 **文件管理**:每用户持久工作区,经 `/files` 浏览 / 预览 / 上传 / 下载 / 删除 / 重命名 / 建目录(路径越狱防护)。
- 📦 **沙箱隔离**:`inprocess`(默认 / CI,**无隔离**)与 `docker`(真隔离:内存 / CPU / PIDs 限额、空闲回收、持久 `/workspace` 卷)两种 provisioner。
- 🎨 **精致前端**:React 19 + Tailwind(浅色 + teal),自绘的 Segmented / Switch / 下拉浮层等控件,Markdown 渲染,响应式聊天界面。

## 架构

四层 + 数据库,服务间用 gRPC,浏览器与后端用 HTTP/SSE:

```mermaid
flowchart LR
  subgraph Browser
    U["SPA — React + Vite<br/>(TanStack Query · Zustand)"]
  end
  subgraph Server
    B["Backend — FastAPI<br/>鉴权 · 会话编排 · 文件 · 技能 · 凭据"]
    W["Worker — agent loop<br/>(gRPC, 持有 LLM 密钥)"]
    S["Sandbox — 隔离容器<br/>(gRPC, 最小信任)"]
  end
  PG[("Postgres")]
  LLM[("OpenAI 兼容 LLM 端点")]
  WS[["/workspace 持久卷"]]

  U -->|"HTTP /api (Vite 代理)"| B
  B -.->|"SSE 回合事件"| U
  B <-->|SQL| PG
  B -->|"gRPC RunTurnStream"| W
  W -->|"HTTP (openai SDK)"| LLM
  W -->|"gRPC ExecTool"| S
  S --- WS
```

**一个回合(turn)的生命周期**:浏览器 `POST /sessions/{id}/turn/stream` → 后端取得会话锁、解析 agent 配置与凭据、确保沙箱就绪 → 调用 worker `RunTurnStream` → worker 循环(调用 LLM → 解析工具调用 → 经沙箱 `ExecTool` 执行 → 回灌结果)→ 事件经 worker→后端→**SSE** 实时回到浏览器 → 结束后落库新消息,必要时压缩历史。

- **Backend** 是**唯一**访问 Postgres 的服务,对外暴露 REST + SSE,对内用 gRPC 调 worker、并经 provisioner 管理沙箱生命周期(创建 / 复用 / 空闲回收)。
- **Worker** 跑 agent 主循环、调用 OpenAI 兼容 LLM、把工具调用转交沙箱;**LLM 密钥只在这一层**。
- **Sandbox** 是最小信任层,只暴露 `ExecTool`,在受限容器里执行工具,工作区挂在持久卷。
- **protos/** 是 gRPC 契约(`worker.proto` / `sandbox.proto`),`packages/common` 是跨服务共享库(编解码、edit 匹配器、事件类型、gRPC 限额等)。

## 信任与安全模型

| 边界 | 规则 |
|---|---|
| 数据库 | 只有 backend 能连 Postgres;worker / sandbox 都不行 |
| LLM 密钥 | 只存在于 worker 进程;按请求注入,绝不下发前端 / 进沙箱 / 写日志 |
| BYO-Key 凭据 | 入库前 AES-256-GCM 加密(主密钥 `AGENT_CLOUD_CREDENTIAL_KEY`);API 只返回掩码 |
| 租户隔离 | 跨租户访问资源返回 **404**(而非 403),不泄露资源是否存在 |
| 沙箱 | 最小信任;docker provisioner 下有内存 / CPU / PIDs 限额、网络可控、空闲回收 |
| 技能包 | 安装时拒绝符号链接(防止把宿主文件吸进技能包再进沙箱) |
| 上传归档 | 默认禁用解压上传归档(`allow_uploaded_archives=false`) |

## 技术栈

- **后端**:Python 3.12、[uv](https://docs.astral.sh/uv/) workspace、FastAPI、SQLAlchemy(async)+ asyncpg、Alembic、Pydantic、gRPC;LLM 走 **OpenAI 兼容**格式([openai](https://github.com/openai/openai-python) SDK,**非** Anthropic SDK)。
- **前端**:React 19、Vite 8、TypeScript、Tailwind CSS(浅色 + teal)、TanStack Query、Zustand、react-markdown + remark-gfm;测试用 Vitest + Testing Library。
- **基础设施**:Postgres 16、Docker(本地起 Postgres + 构建沙箱镜像)、gRPC。

## 仓库结构

```
agent-cloud/
├── services/
│   ├── backend/        # FastAPI + 数据层(唯一访问 Postgres);REST + SSE;沙箱编排
│   ├── worker/         # agent 主循环(gRPC);调用 LLM;持有密钥;经沙箱跑工具
│   └── sandbox/        # 沙箱运行时(gRPC ExecTool);最小信任
├── packages/
│   └── common/         # 跨服务共享:codec / edit 匹配器 / events / tools / types / grpc_limits
├── protos/
│   └── agent_cloud/v1/ # gRPC 契约:worker.proto · sandbox.proto
├── frontend/           # React + Vite SPA(Vite 代理 /api → :8000)
├── deploy/             # sandbox.Dockerfile + entrypoint
├── scripts/            # dev_up.sh(一键全栈) · gen_protos.sh · e2e_real_llm.py
├── docs/               # 架构 / 路线图 / 设计规格(docs/superpowers/specs)
└── pyproject.toml      # uv workspace 根
```

各服务另有独立 README:见 `services/backend/README.md`、`frontend/README.md`。

## 快速开始

### 前置

- **Python 3.12+** 与 **[uv](https://docs.astral.sh/uv/)**(管理 Python 工作区与依赖)
- **Node.js 20+** 与 npm(前端)
- **Docker**(本地起 Postgres、构建并运行沙箱镜像)
- 一个 **OpenAI 兼容**的 LLM 端点 + API Key

### 一键起全栈(推荐)

```bash
# 1) 克隆
git clone https://github.com/wuhaowen0714/agent-cloud.git
cd agent-cloud

# 2) 配置:复制 .env.example 为 .env,至少填 worker 的 LLM 凭据
cp .env.example .env
#   在 .env 里填:
#   AGENT_CLOUD_WORKER_OPENAI_API_KEY=sk-...
#   AGENT_CLOUD_WORKER_OPENAI_BASE_URL=https://<你的-openai-兼容-端点>/v1
#   (启用 BYO-Key 还需 AGENT_CLOUD_CREDENTIAL_KEY,见下方"配置")

# 3) 装前端依赖
( cd frontend && npm install )

# 4) 一键起:Postgres(docker)+ 迁移 + 构建沙箱镜像 + worker + backend + frontend
bash scripts/dev_up.sh
```

打开 **http://localhost:5173**,注册一个账号即可开始。`Ctrl-C` 会清理后台进程与本次起的容器。

> `dev_up.sh` 会以 `docker run --rm` 起 Postgres,**退出即销毁数据**(本地开发用)。需要持久化请改用具名卷或外部 Postgres,并设 `AGENT_CLOUD_DATABASE_URL`。

启动后各端口:前端 `:5173`、后端 `:8000`、worker gRPC `:50052`、Postgres `:5432`。

## 配置

所有后端配置走环境变量,前缀 `AGENT_CLOUD_`(见 `services/backend/src/agent_cloud_backend/config.py`);worker 的 LLM 凭据见 `.env.example`。`dev_up.sh` 会把仓库根 `.env` source 后 export 给所有子进程。

| 变量 | 服务 | 默认 | 说明 |
|---|---|---|---|
| `AGENT_CLOUD_WORKER_OPENAI_API_KEY` | worker | — | 平台默认 LLM 密钥(用户未配 BYO-Key 时用) |
| `AGENT_CLOUD_WORKER_OPENAI_BASE_URL` | worker | — | OpenAI 兼容端点(`.../v1`) |
| `AGENT_CLOUD_WORKER_REQUEST_MAX_TOKENS` | worker | `4096` | 单次输出上限 |
| `AGENT_CLOUD_DATABASE_URL` | backend | `postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud` | Postgres 连接串 |
| `AGENT_CLOUD_AUTH_SECRET` | backend | `dev-insecure-…`(占位) | access JWT 的 HS256 密钥,**生产必须换成长随机串** |
| `AGENT_CLOUD_AUTH_COOKIE_SECURE` | backend | `false` | refresh cookie 是否仅 https 下发;**生产(https)必须 `true`** |
| `AGENT_CLOUD_CREDENTIAL_KEY` | backend | 空 | BYO-Key 的 AES-GCM 主密钥(base64 的 32 字节);**空则凭据功能不可用** |
| `AGENT_CLOUD_SANDBOX_PROVISIONER` | backend | `inprocess` | `inprocess`(无隔离)/ `docker`(真隔离) |
| `AGENT_CLOUD_SANDBOX_IMAGE` | backend | `agent-cloud-sandbox:latest` | 沙箱镜像(由 `deploy/sandbox.Dockerfile` 构建) |
| `AGENT_CLOUD_COMPACTION_TOKEN_THRESHOLD` | backend | `128000` | 历史压缩阈值(建议设为模型窗口的 ~70–80%) |

生成凭据主密钥:

```bash
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

> ⚠️ 真实的 `AGENT_CLOUD_AUTH_SECRET` / `AGENT_CLOUD_CREDENTIAL_KEY` / LLM 密钥只放在本地 `.env`(已被 `.gitignore`),**切勿写进任何被 git 跟踪的文件**。

## 开发

### 后端

```bash
cd services/backend
# 跑测试(用 testcontainers 起临时 Postgres;本环境需禁用 Ryuk)
TESTCONTAINERS_RYUK_DISABLED=true uv run pytest
# 数据库迁移
AGENT_CLOUD_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agent_cloud uv run alembic upgrade head
```

### 前端

```bash
cd frontend
npm run dev      # 开发服务器(:5173,/api 代理到 :8000)
npm run lint     # 类型检查(tsc -b)
npm test         # 单元测试(vitest)
npm run build    # 生产构建
```

### 代码规范 / 协议

```bash
uv run ruff check .            # Python lint(行宽 100,select E/F/I/UP/B)
bash scripts/gen_protos.sh     # 改了 protos/*.proto 后重新生成 gRPC stubs
```

## 工作原理

- **回合(turn)**:后端为每个会话维护带租约的锁,回合进行中周期续租;客户端断开后服务端回合仍在跑,重连可 `resume` 续看(补播 + 实时)。超出上下文窗口会把旧历史**压缩成摘要**后重试;瞬时错误按退避**自动重试**。
- **技能(skills)**:`registry`(`skill_registry/<name>/SKILL.md`)→ **安装**到用户对象库(`users/<uid>/skills/<name>`)+ 写 DB → 在某个 agent 上**启用** → **每回合**把启用集合物化进沙箱 `.skills/<name>/` 并把 `<available_skills>` 注入提示词。"安装"≠"在沙箱里";只有**启用且运行**才物化。内置 `skill-creator` 可脚手架一个 `SKILL.md`,并支持**从工作区**把自制技能一键安装。
- **BYO-Key**:用户在"Provider Keys"里添加凭据 → 加密入库(只回掩码)→ 在 agent 设置里选用某凭据(`key_ref`)→ 回合时后端解出明文,经请求传给 worker 的 provider 工厂;**密钥不落前端、不进沙箱、不入日志**。
- **沙箱 provisioner**:`inprocess` 把沙箱跑在后端进程内(快、**无隔离**,用于默认/CI);`docker` 为每个会话起受限容器(内存/CPU/PIDs 限额、网络可控),工作区挂持久卷,空闲超时回收。依赖(如 `pip install`)会落在 `/workspace` 卷里持久化。

更多设计细节见 `docs/architecture.html` 与 `docs/superpowers/specs/`。

## 路线图

见 `docs/roadmap.html`。已落地:数据层与后端骨架、流式 agent 核心、worker、沙箱(含 docker 隔离)、鉴权与多租户、BYO-Key、文件管理、技能系统、`edit` 工具、前端聊天与设置 UI。后续候选:工具调用修复、`grep`/`find` 工具、Web 工具、MCP 接入、长期记忆等。

## 许可证

尚未指定许可证。在补充 `LICENSE` 之前,默认保留所有权利(All rights reserved)。

---

<sub>后端 / worker / sandbox 三层服务 + Postgres + 沙箱;前端 React + Vite。问题与建议欢迎提 issue。</sub>
