# 主区顶栏(TopBar)设计

**日期:** 2026-06-10
**状态:** 设计已批准

## 目标

主区(侧栏右侧)顶部加一条常驻选项栏,参照 Claude Code 顶栏:左侧 agent/会话面包屑,**最右**是工作区文件按钮(把原来藏在账户菜单里的入口提到一等位置)。

已确认决策:左侧放面包屑;账户菜单的「工作区文件」入口**移除**(单一入口)。

## 设计

- **新组件 `frontend/src/components/TopBar.tsx`**,挂在 `App.tsx` 的 `<main>` 内、`<ChatView>` 之上;认证后**常驻**(无会话也显示——文件抽屉是用户级工作区,与会话无关)。
- **外观**:`shrink-0`、`border-b border-slate-200 bg-white/80 px-4 py-2 backdrop-blur`(与 composer 同视觉语言;`ChatView` 已有 `min-h-0 flex-1`,布局安全)。
- **左侧面包屑**:`agent 名(text-slate-500) / 会话标题(text-slate-800 font-medium, truncate)`;会话标题为空时沿用 `会话 {id 前 6 位}` 自动短名;无会话只显 agent 名,无 agent 留白。数据走订阅式 `["agents", userId]` / `["sessions", userId]` 缓存 + store 的 agentId/sessionId。纯展示(顶栏不做内联改名,侧栏已有)。
- **右侧**:lucide `Folder` 图标按钮(ghost 样式,`h-7 w-7`,`aria-label="工作区文件"`,title 同)→ `toggleFileDrawer()`。
- **AccountMenu**:移除「工作区文件」菜单项与 `Folder` import(菜单剩 Provider Keys / 登出),docstring 同步。

## 非目标(YAGNI)

顶栏内联改名、模型/上下文信息上顶栏、移动端折叠、面包屑可点导航。

## 测试

- `TopBar.test.tsx`:面包屑显示 agent/会话标题;无会话只显 agent 名;点按钮翻转 `fileDrawerOpen`。
- `AccountMenu.test.tsx`:断言「工作区文件」**不再**出现(其余登出流不变)。
