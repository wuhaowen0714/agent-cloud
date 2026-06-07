# Plan 9b: File Management — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A right-side slide-out **file drawer** (user-level, cross-session) over the chat: browse, preview (text/code/image), upload (picker + drag-drop), download, delete, rename, new folder — talking to the Plan 9a `/files` API.

**Architecture:** A top-level "文件" button in the Sidebar toggles `fileDrawerOpen` (Zustand). `FileDrawer` (fixed overlay, mounted in `App`) owns `currentPath` + a TanStack Query `["files", userId, path]`; mutations invalidate it. Pure helpers (size format, breadcrumb, preview-kind) live in `files.ts` and are unit-tested. Spec: [2026-06-07-file-management-design.md](../specs/2026-06-07-file-management-design.md). Depends on Plan 9a.

**Tech Stack:** React 19, TanStack Query v5, Zustand v5, Tailwind (light+teal `brand`), Vitest + RTL. `lint`=`tsc -b`; `test`=`vitest run`.

---

## File Structure

- Modify: `frontend/src/types.ts` — add `FileEntry`.
- Modify: `frontend/src/store.ts` — `fileDrawerOpen` + `toggleFileDrawer`.
- Modify: `frontend/src/api/client.ts` — `listFiles`, `fileRawUrl`, `uploadFiles`, `mkdir`, `moveFile`, `deleteFile`.
- Create: `frontend/src/files.ts` — `formatSize`, `splitBreadcrumb`, `previewKind` (pure).
- Create: `frontend/src/files.test.ts` — unit tests for the helpers.
- Create: `frontend/src/components/files/FileBreadcrumb.tsx`
- Create: `frontend/src/components/files/FileList.tsx`
- Create: `frontend/src/components/files/FilePreview.tsx`
- Create: `frontend/src/components/files/FileToolbar.tsx`
- Create: `frontend/src/components/files/FileDrawer.tsx`
- Create: `frontend/src/components/files/FileButton.tsx`
- Create: `frontend/src/components/files/FileList.test.tsx`
- Modify: `frontend/src/components/Sidebar.tsx` — render `<FileButton/>`.
- Modify: `frontend/src/App.tsx` — render `<FileDrawer/>`.

---

## Task 1: Types, store flag, API client

**Files:** Modify `types.ts`, `store.ts`, `api/client.ts`.

- [ ] **Step 1: Add the `FileEntry` type**

In `types.ts`:

```typescript
export interface FileEntry { name: string; path: string; is_dir: boolean; size: number; mtime: number }
```

- [ ] **Step 2: Add drawer state to the store**

In `store.ts`, add to `AppState` interface, after `live`:

```typescript
  fileDrawerOpen: boolean
```

and to the actions:

```typescript
  toggleFileDrawer: () => void
```

In the `create(...)` body add:

```typescript
  fileDrawerOpen: false,
  toggleFileDrawer: () => set((s) => ({ fileDrawerOpen: !s.fileDrawerOpen })),
```

- [ ] **Step 3: Add file API methods**

In `api/client.ts`, import `FileEntry` (add to the existing `import type { ... } from "../types"`), then add to the `api` object:

```typescript
  listFiles: (userId: string, path: string) =>
    http<FileEntry[]>(`/files?user_id=${userId}&path=${encodeURIComponent(path)}`),
  // 直接给 DOM 用的 URL(<img src> / 下载 <a href>);走 vite 代理的 /api 前缀
  fileRawUrl: (userId: string, path: string, attachment = false) =>
    `/api/files/raw?user_id=${userId}&path=${encodeURIComponent(path)}${attachment ? "&attachment=true" : ""}`,
  uploadFiles: async (userId: string, path: string, files: File[]) => {
    const fd = new FormData()
    for (const f of files) fd.append("files", f)
    const res = await fetch(`/api/files/upload?user_id=${userId}&path=${encodeURIComponent(path)}`, {
      method: "POST",
      body: fd, // 不设 Content-Type,浏览器自动带 multipart boundary
    })
    if (!res.ok) throw new Error(`upload failed: ${res.status} ${await res.text().catch(() => "")}`)
    return (await res.json()) as FileEntry[]
  },
  mkdir: (userId: string, path: string) =>
    http<FileEntry>("/files/mkdir", { method: "POST", body: JSON.stringify({ user_id: userId, path }) }),
  moveFile: (userId: string, src: string, dst: string) =>
    http<FileEntry>("/files/move", { method: "POST", body: JSON.stringify({ user_id: userId, src, dst }) }),
  deleteFile: (userId: string, path: string) =>
    http<void>(`/files?user_id=${userId}&path=${encodeURIComponent(path)}`, { method: "DELETE" }),
```

- [ ] **Step 4: Verify it type-checks**

Run: `cd frontend && npm run -s lint`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/store.ts frontend/src/api/client.ts
git commit -m "feat(frontend): file types, drawer store flag, /files API client"
```

---

## Task 2: Pure helpers (`files.ts`)

**Files:** Create `frontend/src/files.ts`, `frontend/src/files.test.ts`.

- [ ] **Step 1: Write the failing tests**

`files.test.ts`:

```typescript
import { describe, expect, it } from "vitest"
import { formatSize, previewKind, splitBreadcrumb } from "./files"

describe("formatSize", () => {
  it("formats bytes/KB/MB", () => {
    expect(formatSize(512)).toBe("512 B")
    expect(formatSize(2048)).toBe("2.0 KB")
    expect(formatSize(5 * 1024 * 1024)).toBe("5.0 MB")
  })
})

describe("splitBreadcrumb", () => {
  it("always starts at the workspace root", () => {
    expect(splitBreadcrumb("")).toEqual([{ name: "工作区", path: "" }])
  })
  it("accumulates nested paths", () => {
    expect(splitBreadcrumb("a/b")).toEqual([
      { name: "工作区", path: "" }, { name: "a", path: "a" }, { name: "b", path: "a/b" },
    ])
  })
})

describe("previewKind", () => {
  it("detects images by extension", () => {
    expect(previewKind({ name: "p.png", size: 9_000_000 })).toBe("image")
  })
  it("treats small non-images as text and large as download", () => {
    expect(previewKind({ name: "a.txt", size: 100 })).toBe("text")
    expect(previewKind({ name: "big.bin", size: 5_000_000 })).toBe("download")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/files.test.ts`
Expected: FAIL — `./files` not found.

- [ ] **Step 3: Implement the helpers**

`files.ts`:

```typescript
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB", "TB"]
  let v = bytes / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`
}

export interface Crumb { name: string; path: string }
export function splitBreadcrumb(path: string): Crumb[] {
  const crumbs: Crumb[] = [{ name: "工作区", path: "" }]
  let acc = ""
  for (const p of path.split("/").filter(Boolean)) {
    acc = acc ? `${acc}/${p}` : p
    crumbs.push({ name: p, path: acc })
  }
  return crumbs
}

const IMG = new Set(["png", "jpg", "jpeg", "gif", "svg", "webp"])
const TEXT_MAX = 1024 * 1024 // 1 MB:超过只给下载
export type PreviewKind = "image" | "text" | "download"
export function previewKind(entry: { name: string; size: number }): PreviewKind {
  const ext = entry.name.split(".").pop()?.toLowerCase() ?? ""
  if (IMG.has(ext)) return "image"
  return entry.size <= TEXT_MAX ? "text" : "download"
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npx vitest run src/files.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/files.ts frontend/src/files.test.ts
git commit -m "feat(frontend): file helpers (size format, breadcrumb, preview-kind)"
```

---

## Task 3: Breadcrumb + file list

**Files:** Create `components/files/FileBreadcrumb.tsx`, `components/files/FileList.tsx`.

- [ ] **Step 1: FileBreadcrumb**

`components/files/FileBreadcrumb.tsx`:

```tsx
import { splitBreadcrumb } from "../../files"

export function FileBreadcrumb({ path, onNavigate }: { path: string; onNavigate: (p: string) => void }) {
  const crumbs = splitBreadcrumb(path)
  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-slate-100 px-3 py-1.5 text-xs text-slate-500">
      {crumbs.map((c, i) => (
        <span key={c.path} className="flex items-center gap-1">
          {i > 0 && <span className="text-slate-300">/</span>}
          <button
            className={i === crumbs.length - 1 ? "text-slate-700" : "hover:text-brand-600"}
            onClick={() => onNavigate(c.path)}
          >
            {c.name}
          </button>
        </span>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: FileList**

`components/files/FileList.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "../../api/client"
import { formatSize } from "../../files"
import type { FileEntry } from "../../types"

export function FileList({
  entries, userId, onOpenDir, onPreview, onChanged,
}: {
  entries: FileEntry[]
  userId: string
  onOpenDir: (e: FileEntry) => void
  onPreview: (e: FileEntry) => void
  onChanged: () => void
}) {
  const qc = useQueryClient()
  const del = useMutation({
    mutationFn: (e: FileEntry) => api.deleteFile(userId, e.path),
    onSuccess: () => { onChanged(); qc.invalidateQueries({ queryKey: ["files", userId] }) },
  })
  const rename = useMutation({
    mutationFn: ({ e, dst }: { e: FileEntry; dst: string }) => api.moveFile(userId, e.path, dst),
    onSuccess: () => { onChanged(); qc.invalidateQueries({ queryKey: ["files", userId] }) },
  })

  if (entries.length === 0) {
    return <div className="flex-1 p-6 text-center text-sm text-slate-400">空目录</div>
  }
  return (
    <ul className="flex-1 divide-y divide-slate-50 overflow-auto">
      {entries.map((e) => (
        <li key={e.path} className="group flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-slate-50">
          <span className="shrink-0">{e.is_dir ? "📁" : "📄"}</span>
          <button
            className="min-w-0 flex-1 truncate text-left text-slate-700 hover:text-brand-600"
            onClick={() => (e.is_dir ? onOpenDir(e) : onPreview(e))}
            title={e.name}
          >
            {e.name}
          </button>
          {!e.is_dir && <span className="shrink-0 text-xs text-slate-400">{formatSize(e.size)}</span>}
          <span className="flex shrink-0 gap-1.5 text-xs opacity-0 group-hover:opacity-100">
            {!e.is_dir && (
              <a className="text-slate-400 hover:text-brand-600" href={api.fileRawUrl(userId, e.path, true)}>下载</a>
            )}
            <button
              className="text-slate-400 hover:text-brand-600"
              onClick={() => {
                const base = e.path.includes("/") ? e.path.slice(0, e.path.lastIndexOf("/") + 1) : ""
                const next = prompt("重命名为", e.name)
                if (next && next !== e.name) rename.mutate({ e, dst: base + next })
              }}
            >重命名</button>
            <button
              className="text-slate-400 hover:text-red-600"
              onClick={() => { if (confirm(`删除 ${e.name}?${e.is_dir ? "(含其中所有文件)" : ""}`)) del.mutate(e) }}
            >删除</button>
          </span>
        </li>
      ))}
    </ul>
  )
}
```

- [ ] **Step 3: Verify type-check**

Run: `cd frontend && npm run -s lint`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/files/FileBreadcrumb.tsx frontend/src/components/files/FileList.tsx
git commit -m "feat(frontend): file breadcrumb + list (open/preview/download/rename/delete)"
```

---

## Task 4: File preview

**Files:** Create `components/files/FilePreview.tsx`.

- [ ] **Step 1: Implement FilePreview (modal)**

`components/files/FilePreview.tsx`:

```tsx
import { useEffect, useState } from "react"
import { api } from "../../api/client"
import { previewKind } from "../../files"
import type { FileEntry } from "../../types"

export function FilePreview({ userId, entry, onClose }: { userId: string; entry: FileEntry; onClose: () => void }) {
  const kind = previewKind(entry)
  const url = api.fileRawUrl(userId, entry.path)
  const [text, setText] = useState<string | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    if (kind !== "text") return
    let alive = true
    fetch(url).then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
      .then((t) => alive && setText(t)).catch(() => alive && setErr(true))
    return () => { alive = false }
  }, [url, kind])

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-6" onClick={onClose}>
      <div className="flex max-h-[85vh] w-[44rem] max-w-[92vw] flex-col rounded-lg bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <span className="truncate font-mono text-sm text-slate-700">{entry.name}</span>
          <div className="flex shrink-0 gap-3 text-sm">
            <a className="text-brand-600 hover:text-brand-700" href={api.fileRawUrl(userId, entry.path, true)}>下载</a>
            <button className="text-slate-400 hover:text-slate-700" onClick={onClose}>✕</button>
          </div>
        </header>
        <div className="overflow-auto p-3">
          {kind === "image" && <img src={url} alt={entry.name} className="mx-auto max-h-[70vh]" />}
          {kind === "text" && (err
            ? <div className="text-sm text-red-600">无法预览,请下载查看。</div>
            : <pre className="whitespace-pre-wrap break-words font-mono text-xs text-slate-700">{text ?? "加载中…"}</pre>)}
          {kind === "download" && (
            <div className="py-8 text-center text-sm text-slate-500">
              文件较大或为二进制,无法预览。<a className="text-brand-600 hover:underline" href={api.fileRawUrl(userId, entry.path, true)}>点此下载</a>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify type-check**

Run: `cd frontend && npm run -s lint`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/files/FilePreview.tsx
git commit -m "feat(frontend): file preview modal (text/image/download)"
```

---

## Task 5: Toolbar (upload + new folder)

**Files:** Create `components/files/FileToolbar.tsx`.

- [ ] **Step 1: Implement FileToolbar**

`components/files/FileToolbar.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef } from "react"
import { api } from "../../api/client"

export function FileToolbar({ userId, path, onChanged }: { userId: string; path: string; onChanged: () => void }) {
  const qc = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const invalidate = () => { onChanged(); qc.invalidateQueries({ queryKey: ["files", userId] }) }
  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadFiles(userId, path, files),
    onSuccess: invalidate,
  })
  const mkdir = useMutation({
    mutationFn: (name: string) => api.mkdir(userId, path ? `${path}/${name}` : name),
    onSuccess: invalidate,
  })
  return (
    <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-1.5 text-xs">
      <button
        className="rounded bg-brand-600 px-2 py-1 text-white hover:bg-brand-700"
        onClick={() => inputRef.current?.click()}
      >上传</button>
      <input
        ref={inputRef} type="file" multiple className="hidden"
        onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) upload.mutate(fs); e.target.value = "" }}
      />
      <button
        className="rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-50"
        onClick={() => { const n = prompt("新建文件夹名称"); if (n) mkdir.mutate(n) }}
      >新建文件夹</button>
      {upload.isPending && <span className="text-slate-400">上传中…</span>}
    </div>
  )
}
```

- [ ] **Step 2: Verify type-check + commit**

Run: `cd frontend && npm run -s lint` (expect exit 0)

```bash
git add frontend/src/components/files/FileToolbar.tsx
git commit -m "feat(frontend): file toolbar (upload + new folder)"
```

---

## Task 6: Drawer + button + wiring + drag-drop + test

**Files:** Create `components/files/FileDrawer.tsx`, `components/files/FileButton.tsx`, `components/files/FileList.test.tsx`; modify `Sidebar.tsx`, `App.tsx`.

- [ ] **Step 1: FileDrawer (owns path + query, drag-drop to upload)**

`components/files/FileDrawer.tsx`:

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api } from "../../api/client"
import { useStore } from "../../store"
import type { FileEntry } from "../../types"
import { FileBreadcrumb } from "./FileBreadcrumb"
import { FileList } from "./FileList"
import { FilePreview } from "./FilePreview"
import { FileToolbar } from "./FileToolbar"

export function FileDrawer() {
  const open = useStore((s) => s.fileDrawerOpen)
  const toggle = useStore((s) => s.toggleFileDrawer)
  const userId = useStore((s) => s.userId)
  const [path, setPath] = useState("")
  const [preview, setPreview] = useState<FileEntry | null>(null)
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ["files", userId] })

  const { data: entries = [] } = useQuery({
    queryKey: ["files", userId, path],
    queryFn: () => api.listFiles(userId!, path),
    enabled: open && !!userId,
  })

  if (!open || !userId) return open ? null : null
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={toggle} />
      <aside
        className="fixed right-0 top-0 z-50 flex h-full w-[28rem] max-w-[90vw] flex-col border-l border-slate-200 bg-white shadow-xl"
        onDragOver={(e) => e.preventDefault()}
        onDrop={async (e) => {
          e.preventDefault()
          const files = Array.from(e.dataTransfer.files)
          if (files.length) { await api.uploadFiles(userId, path, files); refresh() }
        }}
      >
        <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
          <span className="text-sm font-semibold text-slate-800">文件</span>
          <button className="text-slate-400 hover:text-slate-700" onClick={toggle}>✕</button>
        </header>
        <FileBreadcrumb path={path} onNavigate={setPath} />
        <FileToolbar userId={userId} path={path} onChanged={refresh} />
        <FileList entries={entries} userId={userId} onOpenDir={(e) => setPath(e.path)} onPreview={setPreview} onChanged={refresh} />
        <div className="border-t border-slate-100 px-3 py-1 text-center text-[11px] text-slate-300">拖拽文件到此处上传</div>
      </aside>
      {preview && <FilePreview userId={userId} entry={preview} onClose={() => setPreview(null)} />}
    </>
  )
}
```

(Note: the `enabled: open && !!userId` guard means the query won't run until the drawer is open and a user exists; the early `return` keeps the overlay unmounted when closed.)

- [ ] **Step 2: FileButton**

`components/files/FileButton.tsx`:

```tsx
import { useStore } from "../../store"

export function FileButton() {
  const toggle = useStore((s) => s.toggleFileDrawer)
  const userId = useStore((s) => s.userId)
  if (!userId) return null
  return (
    <button
      className="flex items-center gap-1.5 rounded border border-slate-200 px-2 py-1 text-sm text-slate-600 hover:bg-slate-50"
      onClick={toggle}
    >
      📁 文件
    </button>
  )
}
```

- [ ] **Step 3: Wire into Sidebar and App**

In `Sidebar.tsx`, import and render `<FileButton/>` under the divider (workspace-level, near sessions):

```tsx
import { AgentSelector } from "./AgentSelector"
import { FileButton } from "./files/FileButton"
import { SessionList } from "./SessionList"
import { UserBar } from "./UserBar"

export function Sidebar() {
  return (
    <aside className="flex w-72 flex-col gap-3 border-r border-slate-200 bg-white p-3">
      <div className="text-sm font-semibold text-slate-800">agent-cloud</div>
      <UserBar />
      <AgentSelector />
      <div className="border-t border-slate-100" />
      <FileButton />
      <SessionList />
    </aside>
  )
}
```

In `App.tsx`, render `<FileDrawer/>` as an overlay sibling:

```tsx
import { ChatView } from "./components/ChatView"
import { FileDrawer } from "./components/files/FileDrawer"
import { Sidebar } from "./components/Sidebar"

export default function App() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col bg-slate-50">
        <ChatView />
      </main>
      <FileDrawer />
    </div>
  )
}
```

- [ ] **Step 4: Write a component test for FileList**

`components/files/FileList.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"
import type { FileEntry } from "../../types"
import { FileList } from "./FileList"

const wrap = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)
const dir: FileEntry = { name: "src", path: "src", is_dir: true, size: 0, mtime: 0 }
const file: FileEntry = { name: "a.txt", path: "a.txt", is_dir: false, size: 2048, mtime: 0 }

describe("FileList", () => {
  it("opens a directory vs previews a file, and shows file size", () => {
    const onOpenDir = vi.fn()
    const onPreview = vi.fn()
    render(wrap(<FileList entries={[dir, file]} userId="u1" onOpenDir={onOpenDir} onPreview={onPreview} onChanged={() => {}} />))
    expect(screen.getByText("2.0 KB")).toBeInTheDocument()
    fireEvent.click(screen.getByText("src"))
    expect(onOpenDir).toHaveBeenCalledWith(dir)
    fireEvent.click(screen.getByText("a.txt"))
    expect(onPreview).toHaveBeenCalledWith(file)
  })

  it("shows empty state", () => {
    render(wrap(<FileList entries={[]} userId="u1" onOpenDir={() => {}} onPreview={() => {}} onChanged={() => {}} />))
    expect(screen.getByText("空目录")).toBeInTheDocument()
  })
})
```

- [ ] **Step 5: Run full frontend regression**

Run: `cd frontend && npm run -s lint && npm run -s test`
Expected: `tsc -b` exit 0; all vitest suites pass (existing + `files.test.ts` + `FileList.test.tsx`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/files/ frontend/src/components/Sidebar.tsx frontend/src/App.tsx
git commit -m "feat(frontend): file drawer + button + wiring (browse/upload/preview/manage)"
```

---

## Task 7: Live verification (preview tools)

- [ ] **Step 1: Verify against the running stack**

With the full stack up (`bash scripts/dev_up.sh`), use the preview tools: open the app, set an existing `userId`, click "文件", and confirm: drawer lists the workspace, clicking a dir navigates, clicking a text file previews, upload (picker + drag-drop) adds a file and it appears, new folder works, rename/delete work, download link points at `/api/files/raw?...&attachment=true`. Check `preview_console_logs` (errors) clean. Screenshot for the record.

(Backend Plan 9a must be running for live verification; component/unit tests above don't need it.)

---

## Self-Review

- **Spec coverage:** browse (drawer + list + breadcrumb) ✓; preview text/image/large-download (`FilePreview` + `previewKind`) ✓; upload picker + drag-drop + multifile ✓; download (raw `attachment=true`) ✓; folder download (list "下载" on dirs → `attachment=true` → backend zips) ✓ *(note: FileList "下载" link is rendered for files only; folder zip download is reachable via `fileRawUrl` on a dir — add a dir download affordance if desired)*; mkdir/rename/delete (+confirm) ✓; user-level cross-session (drawer keyed by userId, independent of session) ✓; right-side drawer placement ✓.
- **Type consistency:** `FileEntry` matches backend `FileEntryRead`; `api.*` names used identically across components; query key `["files", userId, path]` consistent (invalidations use the `["files", userId]` prefix).
- **No placeholders:** every step has full code + run command + expected result.
- **Refinement noted:** `previewKind` treats any ≤1 MB non-image as text (binary-under-1MB shows raw bytes) — acceptable v1; a text-extension allowlist can tighten it later. Folder-download affordance in the list is optional polish.
