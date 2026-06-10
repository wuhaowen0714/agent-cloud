# 会话标题自动生成(LLM)设计

**日期:** 2026-06-11
**状态:** 设计已批准

## 目标

会话标题为空时,基于**首条用户提问**用 LLM 自动起名(≤16 字),替代「会话 {id 前缀}」占位;用户手动改过名的永不覆盖。

## 设计

### Worker:新一元 RPC `GenerateTitle`(沿 Summarize/ExtractMemory 先例)

- proto(`worker.proto`):
  - `GenerateTitleRequest { Agent agent = 1; string user_message = 2; }`
  - `GenerateTitleResponse { string title = 1; int64 input_tokens = 2; int64 output_tokens = 3; }`
  - service 加 `rpc GenerateTitle(...)`;`scripts/gen_protos.sh` 重生成。不涉 TurnEvent/codec。
- worker 实现(`server.py` + 新 `title.py`):用 agent 凭据构造 provider(同 Summarize 工厂路径),非流式 `complete()`、`max_tokens=64`;system prompt 要求「为对话起一个简短标题,≤16 字,直接输出标题本身,不要引号/标点收尾/解释」,user 内容 = 首条提问(worker 侧截到前 2000 字符,起名不需要全文)。
- 清洗(worker 侧,`_clean_title`):去首尾空白与成对引号(`"" '' “” 「」`)、换行/连续空白压成单空格、超 50 字符截 47 + `…`;清洗后为空 → 返回空串(由 backend 决定放弃)。

### Backend:回合后异步钩子(同 memory_extract 模式)

- 触发(`turn/runner.py`):回合**成功收尾**(persist 完成)后,若 `session.title is None` → `asyncio.create_task(generate_session_title(session_id, settings=...))`,fire-and-forget,不阻塞回合返回、不挂回合事务。条件不限首回合:失败留 null,下一回合自然重试;生成内容始终基于首条 user 消息。
- 钩子(新 `turn/title.py`):开独立 DB 会话(`get_sessionmaker`):
  1. 载 session;`title is not None` → 直接返回(零 LLM);
  2. 取该会话 seq 最小的 user 消息;无 → 返回;
  3. `resolve_agent_key` 解析 BYO-Key(同 memory_extract;key 仅经 worker);
  4. `generate_title_via_worker(...)`(`worker_client.py` 新函数,gRPC 错误不抛出钩子外);
  5. 清洗后为空 → 放弃;**写前重查 `title is None` 才写**(防生成期间用户手动改名被覆盖),commit。
  - 全程异常 log warning,绝不影响已完成的回合。
- 标题长度天然 ≤50 < PATCH 校验上限 200,无冲突。

### 前端(一行级)

- 标题在回合后异步出现,既有 turn 结束的 `["sessions"]` invalidate 会早于它:`ChatView.consume` 收尾处,**若回合开始前该会话无历史消息**(首回合),`setTimeout` ~3s 后再 invalidate 一次 `["sessions"]` 兜接标题。其余零改动(`title ?? 会话{id}` 回退、重命名入口不变)。

## 非目标(YAGNI)

- 不做截断打底/双阶段升级;不做生成中的 UI 指示;不做失败重试队列(下一回合自然重试);不基于助手回答起名(只用首条提问);不做多语言 prompt 适配(LLM 跟随输入语言)。

## 测试

- worker:`GenerateTitle` handler(fake provider)——清洗(引号/换行/超长截断)、空结果传空串、超长输入截 2000;
- backend:钩子单测(fake worker stub)——成功写入、title 已存在直接返回(不调 worker)、写前二次检查竞态(生成期间被改名 → 不覆盖)、worker gRPC 错误留 null 不抛;runner e2e(既有 fake worker 加 GenerateTitle)——首回合后 session.title 被填、手动改名的会话不被动;
- 前端:首回合 turn_done 后存在延迟二次 invalidate(假定时器);非首回合不延迟刷。
