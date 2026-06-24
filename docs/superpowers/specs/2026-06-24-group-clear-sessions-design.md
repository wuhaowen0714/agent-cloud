# 分组清除会话 — 设计

## 背景
侧边栏会话列表按分组展示(定时任务 / 今天 / 昨天 / 前 7 天 / 前 30 天)。用户要在**每个分组**加一个"清除本组"按钮,一键删除该分组下(当前 agent)的所有会话。现状只有单会话删除(`DELETE /sessions/{id}`)。

## 交互
每个分组标题行(现有可折叠 header)右侧,**hover 时**显示清除按钮(垃圾桶图标,平时隐藏避免误点)。点击 → **内联二次确认**(变红"清除 N 个会话?")→ 再点执行。仅作用于**当前 agent** 的该分组(列表本就只显示当前 agent)。

## 后端
- `POST /sessions/bulk-delete`,body `{session_ids: [uuid...]}`,返回 `{deleted: int, skipped: int}`(skipped = 本人拥有但回合进行中、未删的数量)。
- `SessionRepository.delete_idle_by_ids(user_id, session_ids) -> (deleted, skipped)`:一条 count 查本人拥有数(过滤越权 / 不存在),一条带 status guard 的原子 `delete`(`status=idle` 或租约过期才删,与回合 `try_acquire` 靠行锁串行、无 TOCTOU);`skipped = owned - deleted`。**越权 / 不存在的 id 静默忽略,绝不误删他人**。messages 经 FK CASCADE 连带删。空列表直接返回 (0, 0)。

## 前端
- `api.bulkDeleteSessions(ids) -> {deleted, skipped}`。
- SessionList:分组 header 加清除按钮 + 二次确认状态(useState 记正在确认的分组 label,点别处 / 执行后复位)。执行后 invalidate 刷新;若当前打开会话在被清 id 集里 → `setSession(null)`;`skipped > 0` → 短提示"N 个进行中未删"。

## 测试
- 后端 repo `delete_idle_by_ids`:删多个 idle、跳过 running、越权 id 不删、不存在 id 忽略、空列表。
- 后端端点 `/bulk-delete`:正常删 + 计数、busy 跳过、**越权 id 不删他人会话**(安全回归)。
- 前端 SessionList:分组清除按钮二次确认流程、传对该组 id 集、当前会话被清 → `setSession(null)`。

## 边界
- busy(回合进行中)会话跳过、不阻塞其余,前端提示 skipped 数。
- 越权 / 不存在 id 静默忽略(后端按 `user_id` 过滤,前端只传当前 agent 该组的 id)。
- 二次确认防误触;hover 才显示防误点。
