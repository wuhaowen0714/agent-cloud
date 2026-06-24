# 流式 Subagent 阶段 2 — 前端子 agent 折叠卡片

## 背景
阶段 1 后端把 `subagent_id` + `subagent_started`/`subagent_done` 透传到 SSE,但前端平铺子事件(子 agent 的 web_search/思考看起来像主 agent 自己在搜)。本阶段把同 `subagent_id` 的事件收拢成**折叠卡片**(方案 A:运行中展开看进度,完成后自动折成一行)。

## 实现
- **types.ts**:`TurnEvent` 各事件加 `subagent_id?`,加 `subagent_started`/`subagent_done`。
- **blocks.ts**:`Block` 加 `subagent` 类型 `{ id, description, blocks, running, ok }`;`applyEvent`(把一个事件应用到一组 blocks,顶层与子内部共用)、`startSubagent`/`appendToSubagent`/`finishSubagent`。
- **ChatView feed**:按 `subagent_id` 路由——`subagent_started`/`done` 开关块,带 `subagent_id` 的子事件进对应块内部,其余(顶层主 agent)走 `applyEvent`。重构掉了原先平铺的 thinking/text/tool 分支。
- **TurnBlocks + SubagentCard**(同文件,避免循环 import):蓝色卡片,头 = robot 图标 + "子 agent" + description + 状态(`运行中…` / `✓ N 步`)+ chevron;体折叠,**递归用 TurnBlocks 渲染内部 blocks**;运行中强制展开,完成后默认折叠、点头展开。步数 = 内部工具调用数。
- **messagesToTurns**:历史里子 agent 过程不落库(阶段 1 决定),只剩 `name="task"` 工具块 → 转成折叠的 subagent 卡片(description 取自 args,体 = 结果文本),与 live 视觉一致。

## 安全/边界
- **递归深度**:子 agent 深度封顶 1(阶段 1,子 agent 无 task 工具)→ subagent 块内部不会再有 subagent 块,TurnBlocks 递归只一层,不会无限递归。
- **现有行为**:`applyEvent` 内部就是原 `appendDelta`/`appendToolCall`/`attachToolResult`,顶层事件行为不变(全套回归 321 passed 佐证)。

## 测试
blocks 路由 5(start/append/finish/applyEvent)+ SubagentCard 渲染 3(运行强制展开 / 完成折叠点开 / 失败 ✗)。tsc + vitest 全绿。
