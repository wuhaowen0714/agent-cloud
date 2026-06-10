# 文件夹上传 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 文件抽屉支持整文件夹上传(multipart filename 携带相对路径,后端消毒后嵌套落盘)。

**Architecture:** 后端 `_sanitize_rel_upload_path`(归一/过滤/拒越狱)替换 basename 削平;前端 `uploadFiles` 第三参带 `webkitRelativePath`,工具栏加目录选择 input。store 围栏不变,双层防护。

**Tech Stack:** FastAPI + pytest;React19 + vitest。

参考 spec:`docs/superpowers/specs/2026-06-10-folder-upload-design.md`

---

## Task 1: 后端相对路径上传(TDD)
**Files:** Modify `services/backend/src/agent_cloud_backend/api/files.py`、`services/backend/tests/test_files_api.py`
- [ ] 失败测试:子路径嵌套落盘(含 `?path=d` 拼接)、`../` 400、`\` 归一、basename 不回归 → 实现 `_sanitize_rel_upload_path` + upload 接入 → 过 + ruff → 提交 `feat(backend): folder upload — multipart filenames may carry relative paths`

## Task 2: 前端目录选择 + relativePath(TDD)
**Files:** Modify `frontend/src/api/client.ts`、`frontend/src/components/files/FileToolbar.tsx`;Create `FileToolbar.test.tsx`;Modify `README.md`(特性行)
- [ ] 失败测试:「上传文件夹」按钮 + `webkitdirectory` input 存在、选择触发 `api.uploadFiles` → 实现 → 过 + `npm run lint` → 提交 `feat(frontend): upload-folder button (webkitdirectory)`

## Task 3: 回归 + 审查 + PR
- [ ] 后端全量 + 前端全量 + lint;Fable 5 对抗审查(重点:消毒与 store 围栏的双层一致性、httpx/Starlette multipart filename 边界、覆盖语义);PR → CI 绿 → 等合并指令
