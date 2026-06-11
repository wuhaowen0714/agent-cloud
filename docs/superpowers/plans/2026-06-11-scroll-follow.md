# 聊天滚动粘底跟随 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 流式期间在底部才跟随滚动,上翻即停;「回到底部」浮钮;发送/切会话强制回底。

**Architecture:** 纯前端两文件:新 `scroll.ts`(`isNearBottom` 纯函数)+ `MessageList.tsx`(followRef + onScroll 边界翻转 setState + 条件滚动 + 浮钮);ChatView 给 MessageList 加 `key={sessionId}`。即时滚动替代 smooth。

**Tech Stack:** React19 + vitest(jsdom 几何 mock)。

参考 spec:`docs/superpowers/specs/2026-06-11-scroll-follow-design.md`

---

## Task SF-1: isNearBottom 纯函数(TDD)
**Files:** Create `frontend/src/scroll.ts`、`frontend/src/scroll.test.ts`
- [ ] 失败测试:阈值内 true / 外 false / 恰好 threshold-1 true;实现 `export function isNearBottom(el: { scrollHeight: number; scrollTop: number; clientHeight: number }, threshold = 40): boolean` → 过 → 提交 `feat(frontend): isNearBottom scroll helper`

## Task SF-2: MessageList 跟随逻辑 + 浮钮(TDD)
**Files:** Modify `frontend/src/components/MessageList.tsx`、`frontend/src/components/ChatView.tsx`(key);Test `MessageList.test.tsx`
- [ ] 失败测试(scrollIntoView 原型桩 + 容器几何 defineProperty):默认在底 → live 更新滚动;上翻(几何改远 + fireEvent.scroll)→ live 更新不滚、浮钮「回到底部」出现;点浮钮 → scrollIntoView 调用;live null→带 userText → 强制滚底(此前上翻也滚)。
- [ ] 实现:容器 ref + onScroll(`isNearBottom` → followRef + 边界 setState atBottom);effect `if (followRef.current) endRef.current?.scrollIntoView()`(去掉 smooth);`prevLive` ref 判 null→userText 转变置 follow + 滚底;外层 `relative` 包裹 + `!atBottom` 浮钮(ChevronDown,absolute right-4 bottom-4,白底 ring 阴影圆钮);ChatView `<MessageList key={sessionId} ...>`。
- [ ] `npx vitest run && npm run lint` 全过 → 提交 `fix(frontend): stick-to-bottom scrolling — stop yanking the user during streaming`

## Task SF-3: 回归 + Fable 5 审查 + PR
- [ ] 前端全量 + lint(后端零改动);Fable 5 审查(diff 内联;重点:onScroll 频率与 setState 抖动、程序滚动与用户滚动的状态交互、key 重建的副作用、jsdom 测试的真实性边界)→ 修复 → PR `fix: stick-to-bottom chat scrolling` → CI → 等合并指令
