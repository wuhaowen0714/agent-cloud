# Session 级模型选择 + BYOK 多模型 设计

**目标:** 把"模型选择"从 agent 级下放到 **session 级**——每个会话自己选 provider + model;agent 不再持有任何模型配置。用户 BYOK 时一个 provider 可配多个 model。

**背景(现状):** 模型 100% 是 agent 级:`agent_configs` 存 `model/provider/thinking_level/key_ref`,session 仅靠外键关联 agent。图一底部那个选择器实际改的是 `agent.model`(影响该 agent 所有 session)。`provider` 字段是纯装饰(worker 只看 api_key 是否非空),`thinking_level` 完全未接线。provider credential 只有 name+base_url+key,无"模型清单"概念。worker/proto 本就是"这次调用用什么模型/key",语义可不变——主要改 backend 从 session(而非 agent)读。

**已定决策:** ① 思考档位(thinking_level)**彻底删除**(DB/proto/前端/worker 透传都清,反正未接线);② 平台(sophnet)模型清单走**后端 config**。

---

## 1. 数据模型

### sessions(新增列)
- `model: str`(not null,server_default = 平台默认模型) —— 该会话用的模型名,如 `DeepSeek-V4-Pro`。
- `credential_id: str | None`(nullable,软引用 `provider_credentials.id`) —— `null` = 用平台 sophnet 全局 key;非空 = 用该 BYOK provider 的 key/base_url。
- 不单独存 provider 名:`null → "sophnet"`,否则取 `credential.name`(前端展示用)。

### agent_configs(移除列)
- 删 `model`、`provider`、`thinking_level`、`key_ref`。
- agent 剩:`name`、`enabled_tools`、`permissions`、`context_document`(指令/人设,经 docs)、记忆、技能。agent = "工具集 + 人设 + 记忆"模板,模型与它无关。

### provider_credentials(新增列)
- `models: list[str]`(JSONB,server_default `[]`) —— 该 provider 下可用的模型清单(图三"添加模型",可多个)。
- `name` 即 **provider 名**(图三占位"如 openrouter")。已有 `base_url`/`api_key_encrypted`/`masked` 不变。

### 平台模型(后端 config)
- `Settings` 加 `platform_models: list[str]`(env,逗号分隔)与 `default_model: str`(env,须 ∈ platform_models,否则取首个)。
- 默认值沿用现有前端预设:`DeepSeek-V4-Pro,DeepSeek-V4-Flash,GLM-5.1`,默认 `DeepSeek-V4-Pro`。
- 新端点 `GET /platform/models` → `{ models: [...], default: "..." }`(前端图一 provider=sophnet 时的 model 候选)。

---

## 2. 数据流(provider + model)

**图一两栏(写当前 session):**
1. **Provider 栏**候选 = `["sophnet"(平台)] + 用户每个 credential.name`。
2. 选 `sophnet` → `credential_id=null`,**Model 栏**候选 = `GET /platform/models`;选某 BYOK provider → `credential_id=该 id`,Model 栏候选 = 该 credential.models。
3. 选定后 `PATCH /sessions/{id} { model, credential_id }`(不再 `patchAgent`)。

**回合调用(backend → worker):**
- `build_run_turn_request` 从 **session** 读 `model` + `credential_id`;`credential_id` 非空 → 解密该 credential 的 `api_key`+`base_url`,`null` → 空串(worker 回退全局 sophnet)。填进 `worker.proto` 的 `Agent`(model/provider/api_key/base_url),随 RunTurnRequest 发出。
- 三处辅助 RPC(Summarize/GenerateTitle/ExtractMemory)同样改为从 session 读模型/credential。
- `compaction_threshold_for(model)` 用 session.model(逻辑不变)。
- worker `factory`/`server`/`openai_provider` **不动**(只认 proto 现传的 model/api_key/base_url)。

**新建 session 默认:** `model = 平台默认`、`credential_id = null`(sophnet)。`fork` 复制源 session 的 model+credential_id。

---

## 3. UI 变更

- **图一(Composer)**:`ModelMenu` 改成 **provider + model 两栏**联动,读写**当前 session**。`/model` 斜杠命令同步改为写 session。`useModelOptions` 的"在用模型"来源从 `agents.map(a=>a.model)` 改为 session 的 model + 平台清单 + 各 credential.models。
- **图二(AgentSettings)**:移除 模型/Provider/思考档位/凭据 四块,只剩 名称/指令/工具/记忆/技能。
- **图三(KeysPanel)**:在 名称+base_url+api_key 之外加**模型清单编辑**(加多个 model,可删);保存时连同 `models` 一起 POST。已保存凭据展示其 models。

---

## 4. proto / worker

- `worker.proto` 的 `Agent` message:**删 `thinking_level`**;保留 `model/provider/api_key/base_url`(语义从"agent 配置"变"session 配置")。`provider` 字段 backend 填 provider 名(sophnet 或 credential.name),worker 仍不读(纯日志/将来用)。重新生成 `worker_pb2`。
- worker 侧对 thinking_level/reasoning 的(本就没有的)引用确认清零。

---

## 5. 迁移(alembic,down_revision = 当前 head)

单个迁移,顺序:
1. `sessions` 加 `model`(nullable 临时)、`credential_id`(nullable FK,ondelete SET NULL)。
2. **回填**:`UPDATE sessions SET model = (SELECT model FROM agent_configs WHERE id = agent_config_id)`;`credential_id = (该 agent 的 key_ref,若仍指向存在的 credential 否则 null)`。
3. `sessions.model` 改 not null + server_default = 平台默认(兜底历史空值)。
4. `provider_credentials` 加 `models` JSONB default `[]`。
5. drop `agent_configs` 的 `model`/`provider`/`thinking_level`/`key_ref`。
- downgrade 反向(加回 agent 列、回填、删 session 列)。

---

## 6. 边界与错误处理

- **credential 删除**:现逻辑"清 agent.key_ref"改为"清 session.credential_id"(SET NULL → 回退 sophnet)。`models/session.py` 的 credential_id FK 用 `ondelete=SET NULL` 兜底,API 层也显式清。
- **BYOK provider 无 models**(图三没加模型):Model 栏空 → 前端提示"先给该 provider 添加模型"。
- **平台 config 为空**:`GET /platform/models` 返回兜底 `DeepSeek-V4-Pro`。
- **session.credential_id 越权/失效**:assemble 解 key 时按现有 `resolve_*_key` 逻辑——不属本人或不存在 → 空串 → 回退 sophnet(静默,不报错)。
- **key_ref 归属校验**:现 `_validate_key_ref`(agent_configs.py)的"credential 必须属本人"逻辑挪到 session 写入路径。

---

## 7. 非目标(YAGNI)

- 不接线 thinking_level/reasoning effort(直接删)。
- 不做真正的多-provider SDK 分支:仍是 openai 兼容 + base_url/key 切换(provider 名仅作标识/分组)。
- 不做模型能力自动发现/探测;平台模型靠 config,BYOK 模型靠用户手填。
- 不改 worker 的 client 构造逻辑。

---

## 8. 测试计划

- **backend**:session 新字段读写;`PATCH /sessions` 改 model/credential_id;`POST /sessions` 默认值;assemble/三辅助 RPC 从 session 读;credential 带 models 增删查;删 credential 清 session.credential_id;`GET /platform/models`;迁移回填(老 session 拿到其 agent 的 model)。
- **worker**:proto 去 thinking_level 后 RunTurn/辅助 RPC 仍正常;factory 不受影响。
- **前端**:图一 provider+model 两栏联动 + 写 session;图二无模型相关;图三模型清单增删 + 保存;`useModelOptions` 候选来源;`/model` 斜杠写 session。

---

## 9. 影响文件清单

**后端**:`models/{session,agent_config,provider_credential}.py`、`schemas/{session,agent_config,credential}.py`、`api/{sessions,agent_configs,credentials,user_models?}.py`、新增 `api/platform.py`(或并入)、`turn/{assemble,compaction,title,memory_extract,credentials}.py`、`config.py`、`api/auth.py`(种子)、新 alembic 迁移。
**proto/worker**:`protos/.../worker.proto`(删 thinking_level)+ 重新生成、worker 侧确认无 thinking 引用。
**前端**:`types.ts`、`api/client.ts`、`components/Composer.tsx`、`components/model/*`、`models.ts`、`components/settings/{AgentSettings,KeysPanel}.tsx`、`components/slash/{useSlashCommands,commands}.ts`、`store.ts`、`AgentRail.tsx`。
**测试**:backend `tests/`(sessions/agent_configs/credentials/turn)、前端对应 `*.test.tsx`、worker(若动 proto)。
