# 智能体记忆:自我整合的单块记忆 — 设计

**日期:** 2026-06-09 · **关联:** roadmap P2 · 设计 `docs/superpowers/specs/2026-06-05-stateless-agent-cloud-design.md` §14

**目标(一句话):** 把现在"只追加、按时间取最近 50 条注入"的记忆骨架,升级成 **每个作用域只维护一块、由 LLM 读旧记忆后自行更新/淘汰、有字数上限** 的自整合记忆——让 agent 真正跨会话记住"关于这个人 / 这个 agent"的耐久事实,且不膨胀、不矛盾、不烧 token。

---

## 1. 背景与现状

- 数据层骨架已存在:`memory_entries(scope, owner_id, content, source_session_id)`、`/memory` API(仅 POST 追加 / GET 列出)、回合组装([turn/assemble.py](../../../services/backend/src/agent_cloud_backend/turn/assemble.py))已把记忆作为 `Mem` 注入分层 system 提示词。
- **三个缺口**:① 没有写入路径(除手动 POST 外无人写);② 只能 append,不能更新/淘汰 → 矛盾累积、重复堆积、无界增长;③ 读取是"最近 50 条全量",不是相关性筛选。

## 2. 核心设计:每作用域一块,LLM 读旧记忆后重写

- **两层、每层一块**:`user` 层一块(跨该用户所有 agent),每个 `agent` 一块(仅该 agent)。**没有 session 层**(session 内的事在对话历史里,有压缩兜底)。
  - **agent 层记忆 ≠ agent 指令/人设**(两套独立的东西、独立存储,别混):指令/人设是用户**手写的声明式配置**(`context_documents` type=AGENTS,"你是 X、总是用 Python");agent 层记忆是从对话**学到的、关于这个 agent 工作的事实**(涌现式,"这个 repo 用 pnpm")。
- **写入即对账**:提炼时把 **当前两块 + 本会话新消息** 一起喂给 LLM,让它产出 **更新后的两块**(可新增、改写、淘汰、或判定无变化)。更新/去重/遗忘全部内建在这次重写里。
- **有界**:每块有字数上限(默认见 §10),提示词约束 LLM 控制长度;后端写回前校验、超限截断或重试一次。
- **关键红利:不需要向量检索。** 只有一块、每次全量注入 → 无需 top-k / pgvector / embedding。roadmap P2 的"向量检索"项在本设计下**取消**(将来记忆量真的撑爆单块时,再演进成"核心块总注入 + 归档块向量召回"两级,接口不堵)。

## 3. 数据模型

复用 `memory_entries`,语义从"每行一条事实"改为 **"每行 = 该块的一个完整快照版本"**:

- 字段(在现有基础上):新增 `version INT NOT NULL`;`content` = 整块文本;`source_session_id` = 触发这次重写的会话(溯源)。
- **当前块** = 某 `(scope, owner_id)` 下 `version` 最大的那一行;注入时只取它(`limit=1`)。
- **唯一约束 `(scope, owner_id, version)`** → 提供乐观并发(见 §8)。
- **保留历史**:旧版本行不删(= 版本快照),用于审计/回滚;定期裁剪只保留最近 K 个版本(默认 K=20,可配)。
- **水位线**:`sessions` 表加 `memory_through_seq INT DEFAULT -1`,记录该会话已被提炼进记忆的最大消息 `seq`,镜像现有的 `summary_through_seq`。保证每条消息**最多被提炼一次**、提炼可幂等重试。

> 迁移:alembic 加 `memory_entries.version`(给现有行回填 version=1)+ `sessions.memory_through_seq`。

## 4. 触发时机(两个都做,但带频率闸)

两个触发都走同一条提炼+写入路径,都靠水位线 `memory_through_seq` 去重(每条消息最多提炼一次):

- **空闲提炼**:会话沙箱因空闲达 TTL 将被回收时([main.py](../../../services/backend/src/agent_cloud_backend/main.py) `_reaper_loop`→`reap_idle`),**先提炼再回收**。但**不无脑提炼**——加频率闸:仅当**自上次提炼以来的新对话轮次 ≥ `MEMORY_MIN_ROUNDS`**(默认 10)才提炼,否则跳过(只聊一两句就空闲的不值得花一次 LLM)。
- **压缩前提炼**:压缩([turn/compaction.py](../../../services/backend/src/agent_cloud_backend/turn/compaction.py))把旧历史折叠成摘要**之前**先提炼(否则细节被摘要抹掉)。此处**不设轮次闸**——触发压缩本身就意味着积累了大量历史;覆盖"长期活跃、从不空闲"的会话。
- **轮次**定义 = 自 `memory_through_seq` 以来的用户消息条数。

## 5. 提炼流程与 worker RPC(key 留在 worker)

提炼是一次 LLM 调用,而 **LLM key 只在 worker**——因此**照搬压缩的 `Summarize` 模式**,新增 `ExtractMemory` RPC,backend 编排、worker 执行。

**proto**([protos/agent_cloud/v1/worker.proto](../../../protos/agent_cloud/v1/worker.proto)):
```proto
rpc ExtractMemory(ExtractMemoryRequest) returns (ExtractMemoryResponse);

message ExtractMemoryRequest {
  Agent agent = 1;            // 复用:model/provider/key_ref/api_key/base_url(同回合的解析)
  string user_memory = 2;     // 当前 user 块(可空)
  string agent_memory = 3;    // 当前 agent 块(可空)
  repeated Msg messages = 4;  // 本会话自上次水位线以来的新消息
  int32 soft_max_chars = 5;   // 每块字数【软】上限(只作提示词引导,不硬截断)
}
message ExtractMemoryResponse {
  string user_memory = 1;     // 更新后的 user 块
  string agent_memory = 2;    // 更新后的 agent 块
  bool user_changed = 3;      // 无变化则 backend 跳过写入
  bool agent_changed = 4;
  int64 input_tokens = 5;
  int64 output_tokens = 6;
}
```
> **v1 范围**:只自动提炼 **user 层**——worker 只读/写 `user_memory`、只置 `user_changed`;`agent_memory`/`agent_changed` 字段先保留(置空/false),留给后续 agent 层自动提炼(§13)。`agent_memory` 入参仍可传当前 agent 块,但 v1 worker 不改它。

**数据流**:
1. 触发(空闲/压缩)→ 后端新模块 `turn/memory_extract.py`:取该会话新消息(`seq > memory_through_seq`)、取当前 user/agent 两块、按 `agent.key_ref` 解析 key([turn/credentials.py](../../../services/backend/src/agent_cloud_backend/turn/credentials.py))。
2. 经 [turn/worker_client.py](../../../services/backend/src/agent_cloud_backend/turn/worker_client.py) 调 `ExtractMemory`(模型 = 该 agent 的模型)。
3. worker([server.py](../../../services/worker/src/agent_cloud_worker/server.py) + 新 reconcile 实现)用 §6 的提示词跑 LLM,返回两块 + changed 标志。
4. 后端对 `*_changed=true` 的块**写新版本**(§8),并把 `memory_through_seq` 推进到处理到的最大 seq。

## 6. 重写(reconcile)提示词(v1:仅 user 层)

worker 端 system+user 提示词要点:

- **任务**:给定[当前 user 块][最近对话],输出更新后的 user 块。
- **收什么(user 层 = 跨 agent 的"关于这个人")**:身份/角色/时区/语言、稳定偏好(回复语言、简洁度、代码风格、工具偏好)、长期个人背景/目标。
- **不收**:① 一次性/会话内临时事、低置信、不耐久的(留在对话历史);② **"这个 agent 专属的活儿"**——那属于 agent 层,v1 不自动提(§13)。
- **约束**:① 目标 ≤ **2000 字符(软,见 §10)**,接近预算时合并/丢最不重要的,但**不硬截断**;② **未变更的事实原样保留**,只动需更新/淘汰的(防"传话游戏"漂移);③ 矛盾时新事实覆盖旧的;④ 无耐久事实则原样返回并标 `changed=false`。
- **输出契约**:结构化(块文本 + changed bool),worker 解析失败 → 视为无变化(不破坏现有块)。
- *(将来加 agent 层时,提示词再扩成"user / agent / 都不收"的三分类路由。)*

## 7. 注入(读取)

[turn/assemble.py](../../../services/backend/src/agent_cloud_backend/turn/assemble.py):把 `list_for_context(...)`(最近 50)换成"取该 `(scope, owner)` 的当前块"(latest version, limit 1)。注入仍是 `Mem(scope, content)`,worker 的 `_render_memory` 渲染成 `# Memory` 段不变(现在最多 2 条:user 块 + 该 agent 块)。

## 8. 写入与并发

- **版本快照**:每次写 = `INSERT` 一行 `version = 当前max + 1`。
- **乐观并发**(user 块会被同一用户的多个会话跨 agent 争用):写前读当前 `version=V`;插入 `V+1`;命中唯一约束 `(scope,owner,version)` 冲突 → 说明别人刚写了 → **重读最新块、用它作为"当前块"重跑一次 reconcile**(或退避重试 N 次),避免丢更新。
- **跳过无变化**:`changed=false` 不写,避免版本churn。

## 9. 管理 UI(遗忘/纠错兜底)

- API:`/memory` 改为 `GET ?scope=&agent_id=`(返回当前块)+ `PUT`(用户手动整块替换,写新版本)+ 可选 `DELETE`(清空 = 写空块新版本)。废弃旧的"append 一条"语义。
- 前端:设置抽屉里给"记忆"——user 块在账户/全局处、agent 块在该 agent 设置里;支持查看 / 编辑 / 清空。(可作为独立的收尾 Phase。)

## 10. 配置参数(默认值,均可调)

| 参数 | 默认 | 说明 |
|---|---|---|
| 每块字数**软**上限 | **2000 字符** | **软约束**:写进提示词引导 LLM,后端**不硬截断**;`AGENT_CLOUD_MEMORY_SOFT_CHARS` |
| 空闲提炼最少轮次 | **10** | 自上次提炼以来 < 此轮次则空闲不提炼;`AGENT_CLOUD_MEMORY_MIN_ROUNDS` |
| 提炼用模型 | 该 agent 的 `model` | 复用回合的 provider/key |
| 触发空闲阈值 | 复用沙箱 idle TTL | 或单设 `AGENT_CLOUD_MEMORY_IDLE_SECONDS` |
| 版本保留数 K | 20 | 超出裁剪老版本 |

## 11. 安全与隐私

- 沿用现有租户隔离(`resolve_owner` → 跨租户 404);记忆按 user/agent 归属,backend 独占 DB。
- **key 不出 worker**:提炼经 worker RPC,backend 不直接调 LLM。
- 记忆可能含 PII → 用户可经 UI 查看/清空("遗忘");块内容只进**本人**会话的提示词。

## 12. 测试

- **worker**:`ExtractMemory` 用 mock provider 验证 reconcile 契约——新增/更新/淘汰/无变化/解析失败回退;只提 user 层(跳过非耐久 + 跳过 agent 专属事实);软上限是引导而非硬截断。
- **backend**:版本递增 + 唯一约束并发(两写一冲突→重试不丢更新)、水位线幂等(同消息不二次提炼)、**空闲轮次闸**(< MIN_ROUNDS 不提)、压缩前提炼(折叠前触发)、跳过无变化、注入只取最新块、key 解析复用。
- **前端**:记忆 UI 读/改/清(vitest)。
- 回归全绿才提交(后端 testcontainers + worker 单测 + 前端 vitest)。

## 13. 不在本期范围 / 未来

- **agent 层自动提炼**(v1 不做):agent 层记忆是**独立于指令/人设**的一套"学到的事实"(见 §2)。v1 **只自动提 user 层**——因为从对话里分类"关于人 vs 关于这个 agent 的活儿",比单纯判"是不是关于人的耐久事实"更难、误判率高。agent 块在 v1 仍存在、可经 UI 手动编辑(§9),只是不自动写;将来再开自动提炼(§6 提示词扩成三分类)。
- 向量"归档层"(单块撑爆后再做的两级记忆);后台周期 consolidation/reflection。
- 显式 `remember` 工具(需 worker→backend 回写通道)——本设计先用"自动提炼",工具留后。

## 14. 已定决策

1. **触发**:**两个都做** —— 空闲提炼(带轮次闸 `MEMORY_MIN_ROUNDS`,默认 10,防太频繁)+ 压缩前提炼(不设闸,因为压缩本身意味着积累了大量历史)。见 §4。
2. **agent 层自动提炼**:**v1 只自动提 user 层**;agent 层记忆是独立的东西(≠ 指令/人设),v1 不自动写、可手动编辑,自动提炼留后(§13)。
3. **字数上限**:**2000 字符,软约束**(提示词引导 LLM,后端不硬截断)。见 §10。
