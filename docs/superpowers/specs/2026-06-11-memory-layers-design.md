# 记忆分层(user / agent)设计

**日期:** 2026-06-11
**状态:** 设计已批准(对话中 A+B+C 一起做)

## 背景与问题

用户对 agent 说「记住你叫 nana」,模型调了 `remember(scope='user', content='用户叫我 nana…')`。
user 块跨 agent 共享 → 该用户**所有** agent 都会以为自己叫 nana(污染)。根因三个断层:

1. **工具描述把"身份"放错边**:user 侧写 "identity / role",agent 侧只写 "work or project"——
   agent 自身的名字/人设在描述里无处安放,被 user 侧 "identity" 吸走。
2. **scope 非必填,默认滑进 user**:模型不填 scope 即 user,没有被强迫做层级决策。
3. **注入分层语义极弱**:两层混在一个 `# Memory` 下,仅 `- (user)`/`- (agent)` 前缀;
   模型既不知道 user 块里的"我"不是它自己,也学不到该往哪写。

结构性缺口:自动提炼 v1 只整理 user 块(proto 的 `agent_memory`/`agent_changed` 字段已预留
但未启用)→ agent 层**只进不出**(remember 追加永不去重/合并/淘汰),放错层的事实无人纠正。

## 分层语义

| 层 | owner | 语义 | 判别 |
|---|---|---|---|
| user | user_id(跨 agent 共享) | 关于"这个人":身份、角色、时区、语言、长期偏好/项目 | 换一个 agent 仍成立 → user |
| agent | agent_config_id(单 agent) | 这个 agent 自己:被起的名字/人设、本角色协作约定、职责域长期笔记 | 只对这个 agent 成立 → agent |

(AGENTS 指令文档 = 人工配置层,与"学到的记忆"已分离,不动。)

## 改动

### A. 工具侧 `services/worker/src/agent_cloud_worker/remember.py`

- 重写 `REMEMBER_SPEC.description`:两层语义对齐上表 + 判别句
  ("would this still be true for the user's OTHER agents?") + 显式例子
  (用户给**你**起名/设人设 → scope='agent')+ 措辞要求(写成日后无歧义的形式)。
- `input_schema.required` → `["content", "scope"]`(强迫显式决策)。
- 运行时容错保留:worker execute 与 backend `apply_remember_calls` 对缺失 scope 仍默认
  `user`(兼容历史消息与不守 schema 的模型)。

### B. 注入侧 `services/worker/src/agent_cloud_worker/context.py`

`_render_memory` 拆两节(有则渲染):

```
# Memory — about the user (shared across all of their agents)
<user 块原文>

# Memory — this agent (private to you: your given name/persona, conventions, domain notes)
<agent 块原文>
```

块内容本身已是 markdown bullets,原样输出(去掉旧的 `- (scope)` 行前缀——对多行块本就是
畸形嵌套)。标题措辞与 remember 的 scope 语义一一对应(读写互教)。

### C. 提炼侧(双块 reconcile)

- **worker `memory_extract.py`**:`reconcile_user_memory` → `reconcile_memory`,
  prompt 改双块:两层定义 + 判别句 + **错层事实搬运**(MOVE misfiled facts)+ 各自
  PRESERVE/去重/软上限;输出 STRICT JSON
  `{"user_changed", "user_memory", "agent_changed", "agent_memory"}`;
  解析缺键/错型抛 `MemoryParseError`(语义不变:失败不推水位线)。
- **worker `server.py` ExtractMemory**:传入 `request.agent_memory`,响应回填四字段。
- **backend `turn/memory_extract.py` `extract_session_memory`**:读 agent 块
  (`get_current("agent", s.agent_config_id)`)一并发给 worker;`user_changed`/
  `agent_changed` 各自乐观锁写入 + prune;**任一块冲突 → 整体回滚、不推水位线**
  (与现行单块语义一致,下次重提)。
- **proto 注释**更新(v1 仅 user 层 → 双层);字段不变,无需 codegen。

### 杂项

- README「智能体记忆」特性行:自动提炼改为双层、错层归位。

## 非目标(YAGNI)

- 不做 session 层记忆、不做向量检索、不做记忆条目级 CRUD(仍是每层单块自整合)。
- 不迁移存量错层数据(下次自动提炼会把错层事实搬回正确块)。
- 前端不动(设置页两层记忆的查看/编辑已存在)。

## 测试

- worker:`test_remember.py`(schema required 含 scope;缺 scope 运行时仍默认 user);
  `test_context.py`(两节标题、原文输出、无块不渲染);`test_memory_extract.py`
  (双块解析:都变/只 agent 变/缺键抛/echo 不变块);ExtractMemory handler 既有用例适配。
- backend:`test_memory_extract_orch.py` 适配双字段 fake;新增:agent_changed 写
  agent 块(owner=agent_config_id)+ prune;任一块冲突不推水位线;请求里带上 agent 块现值。
