# 文件预览渲染 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** md/html 预览渲染展示(md 复用聊天 Markdown 组件;html 走 `sandbox="allow-scripts"` 的 opaque-origin iframe)+ 「渲染 / 源码」切换。

**Architecture:** 纯前端:`previewKind` 扩 `markdown|html` 两类;`FilePreview` 按 kind 分支渲染,新增 view 切换 state;失败路径不动。

**Tech Stack:** React19 + react-markdown(现成)+ vitest。

参考 spec:`docs/superpowers/specs/2026-06-10-preview-render-design.md`

---

## Task 1: previewKind 扩类(TDD)
**Files:** Modify `frontend/src/files.ts`、`frontend/src/files.test.ts`
- [ ] 失败测试:`.md→markdown`、`.html→html`、2MB md→download、`.txt→text` 不变 → 实现 → 过 → 提交 `feat(frontend): previewKind learns markdown/html`

## Task 2: FilePreview 渲染分支 + 切换(TDD)
**Files:** Modify `frontend/src/components/files/FilePreview.tsx`、`FilePreview.test.tsx`
- [ ] 失败测试(stub `previewUrl`→"blob:fake"、global fetch→文本、`URL.revokeObjectURL` 兜底 stub):md 渲染出 heading;html 出 iframe(`sandbox==="allow-scripts"`、src=blob);点「源码」出 `<pre>` 原文;既有失败路径不回归 → 实现 → 过 + tsc → 提交 `feat(frontend): render markdown/html previews in-place (sandboxed)`

## Task 3: 回归 + 审查 + PR
- [ ] 前端全量 + tsc;Fable 5 对抗审查(重点:iframe 沙箱属性、XSS 面、blob 生命周期/revoke、切换态与 kind 变化);PR → CI 绿 → 等合并指令
