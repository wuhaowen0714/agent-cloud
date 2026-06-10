# Agent Cloud Frontend

React 19 + Vite 8 + TypeScript + Tailwind(浅色 + teal)的 SPA:流式聊天(SSE 续看)、斜杠命令面板、模型切换 chip、agent/会话管理(一键新建、行内改名/删除)、设置抽屉(Agent / 技能 / 记忆 / Keys)、文件抽屉。

产品特性与架构见仓库根 [README](../README.md)。开发服务器把 `/api` 代理到后端 `:8000`(见 `vite.config.ts`);平时建议直接用仓库根的 `bash scripts/dev_up.sh` 一键起全栈。

## 开发

```bash
npm install
npm run dev      # 开发服务器 :5173(/api → :8000)
npm run lint     # 类型检查(tsc -b)
npm test         # 单元测试(vitest + Testing Library)
npm run build    # 生产构建
```

代码布局:`src/components/`(聊天 / 侧栏 / 设置 / 文件 / `slash/` 命令面板 / `model/` 模型选单 / `ui/` 基元)· `src/api/`(HTTP + SSE + auth)· `src/store.ts`(zustand)· `src/blocks.ts`(回合事件 → 渲染块)。
