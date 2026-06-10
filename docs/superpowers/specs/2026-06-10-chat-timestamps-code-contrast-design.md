# 消息时间戳 + 代码块对比度修复 设计

**日期:** 2026-06-10
**状态:** 设计已批准

## 目标

1. 提问气泡与回答气泡下方显示消息时间。
2. 修复助手消息/文件预览里代码块文字与深色背景对比度过低(看不清)的 bug。

## 设计

### 1. 消息时间戳(纯前端;后端零改动)

后端 `MessageRead` 已返回 `created_at`(Postgres timestamptz → ISO 带时区偏移,前端 `new Date()` 解析无时区坑)。

- **类型**(`types.ts`):`Message` 加 `created_at: string`。
- **分组**(`blocks.ts`):`Turn` 增 `userAt: string | null`(user 消息 created_at)与 `doneAt: string | null`(回合**最后一条**消息 created_at = 回答完成时间);`messagesToTurns` 填充。
- **格式化**(新 `frontend/src/time.ts`):`fmtTime(iso: string): string` —— 与当前时刻比较:今天 → `HH:MM`;今年 → `MM-DD HH:MM`;跨年 → `YYYY-MM-DD HH:MM`(本地时区,24h 制,两位补零)。
- **渲染**(`MessageList.tsx`):提问气泡下方**右对齐**、回答气泡下方**左对齐**,各一行 `text-[11px] text-slate-400`。live 进行中回合:`store.ts` 的 `LiveTurn` 增 `startedAt: string`(`startLive` 时取 `new Date().toISOString()`,确定且可测),用户气泡下显示它;resume 续看(`startLive("")`)无用户气泡,不涉及。助手流式中不显示时间,`turn_done` 后历史刷新自然补上;`unfinished` 回合(取消/出错)用户时间照常显示。
- **非目标**:不显示回合耗时;不做相对时间("x 分钟前",需刷新计时器);不加日期分隔条;中间 tool 消息不单独标时间。

### 2. 代码块对比度(bug 修复)

**根因**:`Markdown.tsx` 的 `prose-code:text-brand-700`(行内代码 teal 色)是 typography 变体,选择器命中 prose 内**所有** `code`——包括代码块的 `<pre><code>`;两边均为零特异性 `:where()`,utility 后加载胜出 → `#0f766e` 深 teal 落在 `prose-pre:bg-slate-800` 深底,对比度 ~1.8:1。

**修复**:className 追加 `[&_pre_code]:text-inherit` —— pre 内 code 继承 pre 的 `text-slate-100`;该任意变体生成带后代选择器的真实特异性,稳压 `:where()`。行内代码 teal 不变。聊天正文与文件预览(同组件)一并修复。

**显式备选已弃**:react-markdown 自定义 code 渲染器(重);浅色代码块主题(深色块是浅色页面的视觉锚点,保留)。

## 测试

- `time.ts`:今天/今年/跨年三档格式、补零。
- `blocks.ts`:`messagesToTurns` 填充 `userAt`/`doneAt`(多消息回合取最后一条;无 user 消息的回合 `userAt` 为 null)。
- `MessageList`:渲染出提问/回答时间;live 流式中助手无时间。
- `Markdown`:包装类名含 `[&_pre_code]:text-inherit`(回归占位;真实对比度由用户视觉确认)。
