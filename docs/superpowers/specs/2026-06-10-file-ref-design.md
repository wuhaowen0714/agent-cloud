# @ 文件引用设计

**日期:** 2026-06-10
**状态:** 设计已批准

## 目标

composer 中输入 `@` 触发工作区文件引用(仿 Codex):弹文件选择浮层、边打边过滤、选中把 `@完整路径 ` 插入消息文本。agent 看到路径自行 `read_file`,**不注入文件内容**(token 友好)。

## 设计

### 后端:`GET /files/index`

递归列出当前用户工作区**全部文件**的相对 posix 路径(仅文件,不含目录):

- `LocalFileStore.walk(user_id, limit)`:`rglob("*")`,**跳过符号链接**(与 `zip_dir` 同款,防越狱读),排序后截断到 `limit`(默认 2000,防巨型工作区);根不存在 → 空表。
- 端点返回 `list[str]`;无入参路径,无越狱面。

### 前端

- **`src/fileRef.ts`(纯函数,单测)**:
  - `atTokenAt(text, caret): { start: number; query: string } | null` —— 光标前当前词以 `@` 开头才触发;`@` 必须在**文本开头或前一字符为空白**(排除邮箱 `xx@yy`);query = `@` 后连续的非空白非 `@` 字符(`[^\s@]*`,**兼容中文文件名**)。
  - `filterPaths(paths, query, max=20)`:不区分大小写子串匹配(路径任意位置),保序截断。
- **`api.indexFiles()`** → `/files/index`;react-query `["fileIndex", userId]`,`staleTime 30_000`(打开面板期间不抖动,新文件最迟 30s 可见)。
- **Composer 接入**:
  - 跟踪 caret(`onChange` / `onSelect` 事件读 `selectionStart`);由 `atTokenAt(text, caret)` 派生文件浮层态。
  - **复用 `SlashPalette` 组件**渲染(item:title=文件名 basename,hint=完整路径);↑↓/Enter/Tab/Esc/IME 守卫与斜杠面板同款键盘路由。
  - 选中:把 `[start, caret)` 替换为 `@路径 `,光标置于其后,焦点保持。
  - **优先级**:`@` 词活跃时文件浮层压过斜杠面板(含 `/model` 参数模式);Esc 关文件浮层(本次词内不再弹,直到词变化)。
  - 无匹配 → 浮层不显示(正常打字)。

### 杂项

- `.gitignore` 增加 `.worktrees/`(多 agent 并行的 worktree 目录)。
- README 特性行提一句 `@ 文件引用`。

## 非目标(YAGNI)

输入框内样式化 chip(需 contenteditable 重写)、模糊评分排序、目录引用、自动注入文件内容、@ 历史/最近使用。

## 测试

- 后端:嵌套文件全列出且为相对 posix 路径;符号链接被跳过;limit 截断;空工作区空表;跨租户(各自只见自己的)。
- 前端:`atTokenAt`(句首/空白后触发、邮箱不触发、中文 query、光标在词中间)、`filterPaths`(大小写/截断);Composer 集成(打 `@` 弹层列文件、过滤、Enter 插入路径+空格、Esc 关闭、`@` 活跃时斜杠面板不出、IME 回车不选中)。
