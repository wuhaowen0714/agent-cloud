# Session 级模型选择 — 实现计划

> 执行方式:controller 逐阶段实现(本环境子 agent 大批量写入会截断),每阶段跑该层全回归 + commit,全部完成后 opus 对抗审查 → PR → 部署 st-e。

**Goal:** 模型选择从 agent 级下放到 session 级;BYOK provider 可配多模型;删除未接线的 thinking_level。

**Architecture:** session 持 `model`+`credential_id`(null=平台 sophnet);agent 去模型字段;credential 加 `models`;平台模型走后端 config。backend 回合时从 session 读模型/key 填 proto,worker 不变。

**Tech Stack:** FastAPI + SQLAlchemy + alembic;gRPC + openai SDK(worker);React + Vite + TS + react-query + zustand。

依赖顺序:**Phase 1(proto)→ 2(数据层+迁移)→ 3(backend API)→ 4(backend turn)→ 5(前端)→ 6(回归+审查+部署)**。后端每阶段可独立跑测试;前端依赖 2-4 的 API。

---

## Phase 1 — proto:删 thinking_level

**文件:** `protos/agent_cloud/v1/worker.proto`、`scripts/gen_protos.sh`(运行)、worker 侧确认。

- [ ] 删 `Agent` message 的 `thinking_level` 字段(保留 model/provider/api_key/base_url)。字段号留空洞(reserved)避免复用。
- [ ] `bash scripts/gen_protos.sh` 重新生成 `worker_pb2`/`pb2_grpc`(backend + worker 两侧)。
- [ ] grep 确认 worker/backend 无残留 `thinking_level` 引用(assemble 等先临时留着,Phase 4 改)。
- [ ] 跑 worker 测试确认 proto 改动不破坏构造(`test_worker_server` 等)。commit `chore(proto): drop unused thinking_level from Agent`.

## Phase 2 — 数据层 + 迁移

**文件:** `models/{session,agent_config,provider_credential}.py`、`models/__init__.py`(确认 import)、`config.py`、新 `alembic/versions/<rev>_session_models.py`。

- [ ] `models/session.py`:加 `model: Mapped[str]`(not null)、`credential_id: Mapped[str|None]`(FK `provider_credentials.id`,ondelete=SET NULL,index)。
- [ ] `models/agent_config.py`:删 `model`/`provider`/`thinking_level`/`key_ref`。
- [ ] `models/provider_credential.py`:加 `models: Mapped[list[str]]`(JSONB,default `list`,server_default `'[]'`)。
- [ ] `config.py`:加 `platform_models: list[str]`(env `AGENT_CLOUD_PLATFORM_MODELS`,CSV 解析,默认 `DeepSeek-V4-Pro,DeepSeek-V4-Flash,GLM-5.1`)+ `default_model`(env,默认 `DeepSeek-V4-Pro`,校验 ∈ platform_models)。`.env.example` 补两行。
- [ ] alembic 迁移(down_revision=当前 head,先 `alembic heads` 查):
  1. add `sessions.model`(nullable 临时)+ `sessions.credential_id`(nullable FK SET NULL)。
  2. 回填 `UPDATE sessions SET model=(SELECT ac.model FROM agent_configs ac WHERE ac.id=sessions.agent_config_id)`;`credential_id=(SELECT ac.key_ref ... )` 仅当 key_ref 指向存在 credential(LEFT JOIN 过滤),否则 NULL。
  3. `ALTER sessions.model SET NOT NULL` + server_default 平台默认(兜底)。
  4. add `provider_credentials.models` JSONB default `'[]'` not null。
  5. drop `agent_configs.{model,provider,thinking_level,key_ref}`。
  - downgrade 反向。
- [ ] 测试:迁移 upgrade/downgrade 不报错(若有迁移测试);model 层字段存在性。commit `feat(db): session model/credential_id, credential models, drop agent model cols`.

## Phase 3 — backend API + schema

**文件:** `schemas/{session,agent_config,credential}.py`、`api/{sessions,agent_configs,credentials}.py`、新 `api/platform.py`、`api/auth.py`、`repositories/session.py`、`main.py`(注册 router)。

- [ ] `schemas/session.py`:`SessionCreate` 加可选 `model`/`credential_id`(默认走 config);`SessionRead` 加 `model`/`credential_id`;`SessionUpdate` 加 `model`/`credential_id`(PATCH)。
- [ ] `schemas/agent_config.py`:三个 schema 删 model/provider/thinking_level/key_ref。
- [ ] `schemas/credential.py`:`CredentialCreate` 加 `models: list[str]=[]`;`CredentialRead` 加 `models`。
- [ ] `api/sessions.py`:`POST` 写 model(默认 `default_model`)+ credential_id(校验属本人,复用 `_validate_credential_id`);新增/扩展 `PATCH /sessions/{id}` 收 model/credential_id;`fork` 复制两字段。`repositories/session.py:create_for` 扩参。
- [ ] 把 `_validate_key_ref`(agent_configs.py)抽成共享 `_validate_credential_owned(user, cred_id)`,session 写入处用。
- [ ] `api/agent_configs.py`:create/patch 去掉模型字段透传;删 `_validate_key_ref`(移走)。
- [ ] `api/credentials.py`:`POST` 存 `models`;`GET` 返回 `models`;`DELETE` 把"清 agent.key_ref"改成"清 session.credential_id"(SET NULL,FK 已兜底但显式清更稳)。
- [ ] `api/platform.py`:`GET /platform/models` → `{models, default}`(读 config)。`main.py` 注册。
- [ ] `api/auth.py`:种默认 agent 去掉 model/provider;种默认 session(若有)带 default_model。
- [ ] 测试(backend `tests/`):session create 默认/显式 model+cred、patch model+cred、cred 校验属本人、fork 带模型;agent create/patch 无模型字段;credential 带 models 增删查;删 cred 清 session.credential_id;`GET /platform/models`。逐组 commit。

## Phase 4 — backend turn(从 session 读模型/key)

**文件:** `turn/{assemble,compaction,title,memory_extract,credentials}.py`、`api/turn.py`。

- [ ] `turn/credentials.py`:`resolve_agent_key`→泛化 `resolve_session_key(session)`(按 session.credential_id 解密;null/越权→`("","")`)。
- [ ] `turn/assemble.py:build_run_turn_request`:从 session 读 model + credential_id,填 proto Agent(model/provider=cred.name|"sophnet"/api_key/base_url),不再填 thinking_level。provider 名供日志。
- [ ] `turn/{compaction,title,memory_extract}.py`:三处辅助 RPC 同样从 session 读模型/key(它们已有 session 上下文或可取)。
- [ ] `api/turn.py:maybe_compact_after_turn`:model 来源对齐 session(经 assemble 已填)。`compaction_threshold_for(session.model)`。
- [ ] 测试:assemble 用 session 的 model/cred;空 cred→空 key;辅助 RPC 同。commit `feat(turn): drive model+credential from session not agent`.

## Phase 5 — 前端

**文件:** `types.ts`、`api/client.ts`、`models.ts`、`components/model/*`(ModelMenu/useModelOptions)、`components/Composer.tsx`、`components/settings/{AgentSettings,KeysPanel}.tsx`、`components/slash/{useSlashCommands,commands}.ts`、`AgentRail.tsx`、`store.ts`。

- [ ] `types.ts`:`Session` 加 `model`/`credential_id`;`AgentConfig` 删模型字段;`Credential` 加 `models`。
- [ ] `api/client.ts`:`createSession`/`patchSession` body 加 model+credential_id;`createCredential` 加 models;新增 `getPlatformModels()`;`patchAgent`/`createAgent` 去模型字段。
- [ ] `models.ts`/`useModelOptions`:候选改为「provider 维度」——平台(getPlatformModels)+ 各 credential.models;**不再合并 user_models/agents.model**。导出 provider 列表(sophnet + credentials.name)。
- [ ] **图一(Composer + ModelMenu)**:两栏联动(provider→model);读写**当前 session**(`patchSession`,失效 sessions 查询);chip 显示 `provider · model`。`/model` 斜杠 + `setModel` 改写 session。
- [ ] **图二(AgentSettings)**:删 模型/Provider/思考档位/凭据 四块。
- [ ] **图三(KeysPanel)**:加「模型」多值编辑(加/删 model 行),保存连同 models;已存凭据展示 models。
- [ ] `AgentRail.tsx`:createAgent 去 DEFAULT_MODEL。
- [ ] 测试(`*.test.tsx`):Composer 两栏联动+写 session;AgentSettings 无模型;KeysPanel 模型增删+保存;useModelOptions 候选来源;useSlashCommands `/model` 写 session。`npm run lint` + `vitest`。逐组 commit。

## Phase 6 — 收尾

- [ ] 全回归:backend(`pytest -m "not docker"` 各包)、worker、前端(lint+vitest)。
- [ ] opus 对抗审查(重点:迁移回填正确性、credential 越权校验、session/agent 解耦无遗漏、前端两栏联动边界)。修 Critical/High。
- [ ] PR → CI → 合并 → 部署 st-e(改了 proto+backend+前端 → app+web 镜像重建;sandbox 未改 cache hit;清华源+timeout)。验证 worker/web 刷新 + `GET /platform/models` 通 + 真机选模型。

---

## Self-review 检查
- 覆盖 spec 全部 9 节 ✅(数据/数据流/UI/proto/迁移/边界/非目标/测试/文件)。
- 顺序无环:proto→db→api→turn→fe→收尾。
- thinking_level 删除点:proto(P1)、db+agent(P2)、schema(P3)、assemble(P4)、前端 AgentSettings(P5)——全覆盖。
- user_models 废弃:P5 useModelOptions 不再合并(后端表留)。
- 风险点:迁移回填依赖 agent 列(故先回填再 drop,同一迁移内顺序保证);credential 删除的引用清理从 agent 改 session。
