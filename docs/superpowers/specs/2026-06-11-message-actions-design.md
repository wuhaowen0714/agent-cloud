# 消息级操作:复制 / 回滚 / Fork — 设计

**日期**:2026-06-11
**目标**:在聊天消息上提供 hover 操作(参考 Claude.ai 用户消息的三按钮):**复制**消息、**回滚**会话到某条用户消息之前、从某条用户消息**fork** 出新会话。回滚与 fork **只动会话(消息),不动文件**。

## 选型结论

**扁平硬删 + 复制式 fork**(评审采纳):回滚直接 `DELETE` 消息后缀;fork 把前缀复制进一个新的扁平会话。零 schema 改动,复用现有 `messages`/`sessions` 表。回滚是销毁性的——fork 即其非销毁逃生口。

放弃的备选:分支树(parent_message_id/软删)需大改 schema 且 `build_run_turn_request`/`list_by_session`/压缩/记忆全得改写,为当前需求过度工程;引用式 fork 打破 `(session_id, seq)` 与 CASCADE,不可取。

## 三个操作的语义

### 复制(纯前端,无后端)
- `navigator.clipboard.writeText(text)`。
- **用户消息**:复制其文本(`content.text`)。**助手消息**:复制其正文(`content.text`,不含 tool_calls/tool_results 噪音)。
- 挂在用户消息**和**助手消息上。

### 回滚 `POST /sessions/{session_id}/rollback` body `{message_id}`
- 仅挂用户消息。语义:**回到"发这条之前"**——删掉这条用户消息及其之后的全部消息,并把这条文本回填到输入框,可改了重问(Claude.ai 行为)。
- 后端:
  1. `owned_session` 校验归属(否则 404)。
  2. 查 `message_id`:必须属于本会话且 `role == "user"`,否则 422;取其 `seq`(= `target`)。
  3. **会话锁**:与回合/压缩同一把锁。会话 `running` → 409 `session is busy`(回滚是销毁性写,必须串行)。抢到锁后在锁内执行,收尾 `release`(参考 `compact_session` 的 try_acquire→commit→...→finally release 模式)。
  4. `DELETE FROM messages WHERE session_id = ? AND seq >= target`。
  5. **修压缩/记忆游标**:
     - `summary`:若 `target <= summary_through_seq`(摘要折叠了已被删的消息)→ `summary = ""`、`summary_through_seq = -1`(下次回合按需重压);否则不动。
     - `memory_through_seq = min(memory_through_seq, target - 1)`(survivors 不重复提炼,新加消息能被提炼;已写入共享记忆块的事实保持不变——符合"不回滚文件/记忆")。
     - `last_context_tokens` 置 `NULL`(旧值已不反映新历史)。
  6. 返回 `{deleted_count, user_text}`(`user_text` = 被删那条 user 消息的文本)。
- 前端:成功 → `qc.invalidate(["messages", sid])` + `qc.invalidate(["sessions"])` + 把 `user_text` 写入 `composerDraft`(回填输入框)。

### Fork `POST /sessions/{session_id}/fork` body `{message_id}`
- 仅挂用户消息。语义:**与回滚对称,但落在新会话**——新建会话,复制这条用户消息**之前**(`seq < target`)的全部历史,在新会话回填这条文本,切过去;**原会话原样保留**。
- 后端:
  1. `owned_session` 校验(404)。
  2. 查 `message_id`:属于本会话且 `role == "user"`,否则 422;取 `target`。
  3. **只读原会话**,允许其在跑(读已提交消息的快照,不抢锁)。
  4. 新建 `Session`:同 `user_id`、`agent_config_id`、`work_subdir`(共用用户工作区);`title` = 原标题 +「(分支)」(原标题为空则留空,走异步起名)。
  5. 复制 `seq < target` 的消息到新会话(保序、保 `seq`/`role`/`content`/`model`/`tokens`)。
  6. 新会话游标:若 `summary_through_seq < target` → 连 `summary`/`summary_through_seq` 一起复制(摘要只覆盖被复制的消息);否则 `summary=""`、`summary_through_seq=-1`。`memory_through_seq = min(原, target - 1)`。`last_context_tokens = NULL`。
  7. 返回 `{new_session_id, user_text}`。
- 前端:成功 → `qc.invalidate(["sessions"])` + `setSession(new_session_id)` + 把 `user_text` 写入 `composerDraft`。

## 文件语义
回滚/fork 都不碰文件。工作区是**用户级共享**(`base_root/<user_id>/workspace`,所有会话共用,现状如此),所以 fork 出的分支与原会话看到同一份文件。本设计**不**引入每会话文件隔离(那是独立的大工程)。

## 前端接线
- **store**:新增 `composerDraft: string | null` + `setComposerDraft(text|null)`。`Composer` 用 effect 消费:`composerDraft` 非空时写进自身 `text` state 并 `setComposerDraft(null)` 清空(避免重复回填)。`logout`/切用户重置为 `null`。
- **MessageList**:每个气泡加 hover 操作行。复制(用户+助手);回滚、fork(仅用户气泡)。`ChatView` 下传 `onRollback(messageId)`、`onFork(messageId)`(与现有 `onRetry` 同模式),内部调 API client → 成功后做上面的 invalidate/setSession/setComposerDraft。
- **api client**:`rollbackSession(id, messageId)`、`forkSession(id, messageId)`。
- 复制不经 ChatView,`MessageList` 直接 `navigator.clipboard.writeText`(失败吞掉或轻提示)。

## 错误处理
- 会话在跑 → 回滚 409(前端提示"会话正忙,请稍候再试";不阻塞 fork)。
- `message_id` 不属本会话 / 非 user 角色 → 422。
- 会话不存在/不属本人 → 404。
- 复制:clipboard API 不可用时静默失败(或一行 flash),不报错。

## 测试
**后端**(`cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker"`):
- 回滚:删 `seq >= target` 后缀;`target <= summary_through_seq` 时重置摘要,否则保留;`memory_through_seq` 钳到 `target-1`;返回 user_text。
- 回滚锁冲突:会话 `running` → 409。
- 回滚所有权/角色:跨会话 message → 422/404;非 user → 422。
- fork:新会话复制 `seq < target` 前缀、独立于原会话;摘要按 `summary_through_seq < target` 决定复制与否;原会话不变;标题带「(分支)」。
- fork 不受原会话 running 影响(只读快照)。

**前端**(`npm test` / `npm run lint`):
- hover 按钮出现位置:用户气泡三个、助手气泡仅复制。
- 复制调 `clipboard.writeText` 且内容正确。
- 回滚/fork 调对应 API、成功后写 `composerDraft`(回填);fork 还 `setSession` 新 id。
- `composerDraft` → Composer 回填 effect:消费一次即清空。
- store:`composerDraft` set/clear、logout 重置。

## 范围外(YAGNI)
- 撤销回滚 / 分支树导航 / 多分支可视化。
- 每会话文件隔离、fork 复制工作区。
- 编辑助手消息、重试助手消息(本仓库已有 turn 重试入口)。

## 工作流
worktree(已建 `worktree-feat-message-actions`)+ 简要 plan + TDD + Fable 5 对抗审查 + PR。
