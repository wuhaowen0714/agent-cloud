# 子 agent 显示增强(提示词 + 执行过程持久化)设计

> 子 agent 折叠卡当前只显示 description + 最终输出。用户反馈刷新后看不到主 agent 给子 agent 的
> **提示词**、也看不到子 agent 的**执行过程**(web_search/思考)。本设计补这两点。

## 现状

- **执行过程**:子 agent 中间消息不落库(阶段 1 设计,产出折进 task 结果);live 流式能看、刷新后丢失,
  历史 `messagesToTurns` 只用 task result text 重建。
- **提示词**:卡头只显示 `description`;`SubagentStarted` 只带 description 不带 prompt;live 时 task 的
  `tool_call_start`(args 含 prompt)被 C1 修复拦截、没用上。

## A. 提示词显示(小改)

- proto `SubagentStarted` 加 `string prompt`;common `SubagentStarted` + `codec` 带 prompt;
  worker `SubagentExecutor.execute` emit 时带 `prompt=prompt`(已有局部变量)。
- backend SSE `subagent_started` 透传 prompt(`sse.py` + `turn_event_from_proto`)。
- frontend:`subagent_started` 事件 + subagent 块加 `prompt`;`startSubagent(blocks,id,description,prompt)`;
  `messagesToTurns` 历史从 task `args.prompt` 取;`SubagentCard` 卡体顶部折叠"任务指令"区显示 prompt。

## B. 执行过程持久化(中改,跨层)

**数据模型**:子 agent 中间消息(assistant/tool)作为**独立 message 行**落库,`content` 里带
`parent_call_id`(= task 工具调用的 call_id;存进 content JSONB,**不动 DB schema、无 migration**)。

- proto `Msg` 加 `string parent_call_id = 5`;common `Message` 加 `parent_call_id: str = ""`;
  codec `msg_to_proto`/`msg_from_proto` 带该字段。
- worker `SubagentExecutor` 累积 `accumulated_sub_messages`(子 `TurnDone.new_messages`,每条标
  `parent_call_id = call.id`);`server.py:343` 主 TurnDone 时把它并入 `event.new_messages`(已在此累加 usage)。
- backend `common_to_content`/`content_to_common` 带 parent_call_id;`_persist` 落库子消息(按 append 顺序分配 seq)。
- frontend `MessageContent` 加 `parent_call_id?`;`messagesToTurns` 先把带 parent_call_id 的消息抽出、
  按 parent_call_id 分组,重建成子 blocks 塞进对应 task 的 subagent 卡(而非顶层)。

## 取舍

- 不动 DB schema(parent_call_id 走 content JSONB)。
- 子消息落库增存储(一次子 agent 几条~几十条消息);live 流式不变,本设计补的是**刷新后的历史重建**。
- 子消息在主回合 `new_messages` 末尾(用 parent_call_id 关联,不依赖 seq 位置)。
- post-persist 副作用(schedule/remember)只认主 agent 消息:子消息带 parent_call_id,副作用扫描应跳过
  (子 agent 不能 schedule/不暴露 task,实际无 schedule_task 调用;remember 是工具,子 agent 有但产物
  应归子上下文 —— 落库即可,主回合副作用不重复处理子消息)。

## 测试

- common:`msg_to_proto`/`from_proto` parent_call_id 往返;`SubagentStarted` prompt 往返。
- worker:`SubagentExecutor` 暴露 `accumulated_sub_messages`(带 parent_call_id) + emit prompt。
- backend:`common_to_content`/`content_to_common` parent_call_id 往返。
- frontend:`messagesToTurns` 按 parent_call_id 重建子 blocks 进卡;`SubagentCard` 显示 prompt。

## 部署

worker + backend + frontend 都改 → **app 镜像 + web 镜像**重建(完整 deploy.sh)。
