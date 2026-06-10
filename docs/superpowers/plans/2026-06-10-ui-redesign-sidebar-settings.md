# 前端 UI 重设计(侧边栏 + 设置抽屉)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把侧边栏改成 Notion 柔和、设置抽屉改成「左导航 + 分组设置行」,并用 lucide-react 线性图标替掉所有 emoji——纯表现层,逻辑/数据/store/api 不动。

**Architecture:** 先建共享底座(lucide 依赖 + `SettingGroup`/`SettingRow`/`SettingsNav` 三个基元),再逐个重排/重绘消费组件。**restyle 任务一律保留原有 state/mutation/query 逻辑,只换 JSX 结构与 className**;精确的 Tailwind 细节在实现时配合 live-verify 收敛(本计划给出目标结构、关键类、图标映射、需保留的逻辑、测试更新点)。

**Tech Stack:** React19 + TS + Tailwind(brand=teal,色阶 50–900;shadow card/pop)+ lucide-react + zustand + react-query + vitest/@testing-library。

参考 spec:`docs/superpowers/specs/2026-06-10-ui-redesign-sidebar-settings-design.md`

---

## 文件结构

**新增**
- `frontend/src/components/ui/SettingGroup.tsx` — 分组卡(可选小标题 + 软边框 + 行分隔)
- `frontend/src/components/ui/SettingRow.tsx` — 设置行(label/hint 左、控件右;block 变体)
- `frontend/src/components/ui/SettingGroup.test.tsx` — 基元渲染测试
- `frontend/src/components/settings/SettingsNav.tsx` — 设置抽屉左侧竖排图标导航
- `frontend/src/components/settings/SettingsNav.test.tsx`

**修改**
- `frontend/package.json`(+ lucide-react)
- `frontend/src/components/ui/index.ts`(导出新基元)
- `frontend/src/components/settings/SettingsDrawer.tsx`(左导航壳)
- `frontend/src/components/settings/AgentSettings.tsx`(分组行,逻辑不变)
- `frontend/src/components/settings/SkillsPanel.tsx` / `KeysPanel.tsx` / `MemoryPanel.tsx`(分组行)
- `frontend/src/components/Sidebar.tsx` / `AgentList.tsx` / `SessionList.tsx` / `AccountMenu.tsx`(Notion 柔和 + 图标)
- `frontend/src/components/Sidebar.test.tsx`(「＋ 新对话」→「新对话」)

全程命令在 `frontend/` 下:`npx tsc --noEmit`、`npx vitest run <file>`。

---

## Task 1: 引入 lucide-react

**Files:** Modify `frontend/package.json`(+lock)

- [ ] **Step 1: 安装**

Run: `cd frontend && npm install lucide-react`
Expected: 写入 `dependencies`,无报错。

- [ ] **Step 2: 冒烟校验可导入**

Run: `cd frontend && node -e "import('lucide-react').then(m=>console.log(!!m.Plus, !!m.X, !!m.Bot, !!m.Blocks, !!m.Brain, !!m.KeyRound, !!m.Folder, !!m.LogOut, !!m.ChevronDown, !!m.Settings2))"`
Expected: `true true true true true true true true true true`(用到的图标都存在)。

- [ ] **Step 3: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/package.json frontend/package-lock.json
git commit -m "build(frontend): add lucide-react for the icon system

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `SettingGroup` + `SettingRow` 基元

**Files:** Create `ui/SettingGroup.tsx`, `ui/SettingRow.tsx`, `ui/SettingGroup.test.tsx`; Modify `ui/index.ts`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/ui/SettingGroup.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { SettingGroup } from "./SettingGroup"
import { SettingRow } from "./SettingRow"

describe("SettingGroup / SettingRow", () => {
  it("渲染分组标题与行内 label + 控件", () => {
    render(
      <SettingGroup label="基本">
        <SettingRow label="名称" hint="给它起个名">
          <input aria-label="名称输入" />
        </SettingRow>
      </SettingGroup>,
    )
    expect(screen.getByText("基本")).toBeInTheDocument()
    expect(screen.getByText("名称")).toBeInTheDocument()
    expect(screen.getByText("给它起个名")).toBeInTheDocument()
    expect(screen.getByLabelText("名称输入")).toBeInTheDocument()
  })

  it("block 行也渲染 label + children", () => {
    render(
      <SettingRow label="工具" block>
        <button>bash</button>
      </SettingRow>,
    )
    expect(screen.getByText("工具")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "bash" })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/ui/SettingGroup.test.tsx`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 实现 `SettingGroup.tsx`**

```tsx
import type { ReactNode } from "react"

// 一组设置:可选低对比小标题 + 软边框圆角卡(行间细分隔线)。
export function SettingGroup({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      {label && (
        <div className="px-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
          {label}
        </div>
      )}
      <div className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200/80 bg-white">
        {children}
      </div>
    </section>
  )
}
```

- [ ] **Step 4: 实现 `SettingRow.tsx`**

```tsx
import type { ReactNode } from "react"

// 一行设置:label(+hint)在左、控件在右;block=true 时控件整行铺开(宽输入/文本域/chip 组)。
export function SettingRow({
  label,
  hint,
  block = false,
  children,
}: {
  label: string
  hint?: string
  block?: boolean
  children: ReactNode
}) {
  return block ? (
    <div className="px-3.5 py-3">
      <div className="text-sm text-slate-700">{label}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-400">{hint}</div>}
      <div className="mt-2">{children}</div>
    </div>
  ) : (
    <div className="flex items-center justify-between gap-4 px-3.5 py-3">
      <div className="min-w-0 max-w-[45%] shrink-0">
        <div className="truncate text-sm text-slate-700">{label}</div>
        {hint && <div className="truncate text-xs text-slate-400">{hint}</div>}
      </div>
      <div className="flex min-w-0 flex-1 items-center justify-end gap-2">{children}</div>
    </div>
  )
}
```

- [ ] **Step 5: 导出**

Edit `frontend/src/components/ui/index.ts` — 追加:

```ts
export { SettingGroup } from "./SettingGroup"
export { SettingRow } from "./SettingRow"
```

- [ ] **Step 6: 跑测试 + tsc**

Run: `cd frontend && npx vitest run src/components/ui/SettingGroup.test.tsx && npx tsc --noEmit`
Expected: PASS + tsc 0 错。

- [ ] **Step 7: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/ui/SettingGroup.tsx frontend/src/components/ui/SettingRow.tsx frontend/src/components/ui/SettingGroup.test.tsx frontend/src/components/ui/index.ts
git commit -m "feat(frontend): SettingGroup + SettingRow primitives

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `SettingsNav`(设置左导航)

**Files:** Create `settings/SettingsNav.tsx`, `settings/SettingsNav.test.tsx`

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/settings/SettingsNav.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { SettingsNav } from "./SettingsNav"

describe("SettingsNav", () => {
  it("渲染 4 个 tab,点击回调对应 id", () => {
    const onSelect = vi.fn()
    render(<SettingsNav tab="agent" onSelect={onSelect} />)
    for (const name of ["Agent", "技能", "记忆", "Provider Keys"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument()
    }
    fireEvent.click(screen.getByRole("button", { name: "记忆" }))
    expect(onSelect).toHaveBeenCalledWith("memory")
  })

  it("当前 tab 高亮(aria-current)", () => {
    render(<SettingsNav tab="skills" onSelect={() => {}} />)
    expect(screen.getByRole("button", { name: "技能" })).toHaveAttribute("aria-current", "true")
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/settings/SettingsNav.test.tsx`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 实现 `SettingsNav.tsx`**

```tsx
import { Blocks, Bot, Brain, KeyRound } from "lucide-react"
import type { ComponentType } from "react"
import type { SettingsTab } from "../../store"

const TABS: {
  id: SettingsTab
  label: string
  Icon: ComponentType<{ size?: number; className?: string }>
}[] = [
  { id: "agent", label: "Agent", Icon: Bot },
  { id: "skills", label: "技能", Icon: Blocks },
  { id: "memory", label: "记忆", Icon: Brain },
  { id: "keys", label: "Provider Keys", Icon: KeyRound },
]

export function SettingsNav({
  tab,
  onSelect,
}: {
  tab: SettingsTab
  onSelect: (t: SettingsTab) => void
}) {
  return (
    <nav className="flex w-36 shrink-0 flex-col gap-0.5 border-r border-slate-100 p-2">
      {TABS.map(({ id, label, Icon }) => {
        const active = id === tab
        return (
          <button
            key={id}
            type="button"
            aria-current={active}
            onClick={() => onSelect(id)}
            className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition ${
              active ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            <Icon size={16} className={active ? "text-brand-600" : "text-slate-400"} />
            <span className="truncate">{label}</span>
          </button>
        )
      })}
    </nav>
  )
}
```

- [ ] **Step 4: 跑测试 + tsc**

Run: `cd frontend && npx vitest run src/components/settings/SettingsNav.test.tsx && npx tsc --noEmit`
Expected: PASS + tsc 0 错。(`aria-current={active}` 渲染为 `aria-current="true"/"false"`。)

- [ ] **Step 5: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/settings/SettingsNav.tsx frontend/src/components/settings/SettingsNav.test.tsx
git commit -m "feat(frontend): SettingsNav left-rail (lucide icons)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `SettingsDrawer` → 左导航壳

**Files:** Modify `settings/SettingsDrawer.tsx`

逻辑保留:open/userId 守卫、backdrop 关闭、按 tab 渲染四个面板(含 memory 的 user-scope props)。变化:顶部下划线 tab → 左侧 `SettingsNav`;宽度 `w-[30rem]`→`w-[32rem]`;关闭 ✕ → `<X>`。

- [ ] **Step 1: 整体替换 `SettingsDrawer.tsx`**

```tsx
import { X } from "lucide-react"
import { useStore, type SettingsTab } from "../../store"
import { AgentSettings } from "./AgentSettings"
import { KeysPanel } from "./KeysPanel"
import { MemoryPanel } from "./MemoryPanel"
import { SettingsNav } from "./SettingsNav"
import { SkillsPanel } from "./SkillsPanel"

export function SettingsDrawer() {
  const open = useStore((s) => s.settingsOpen)
  const close = useStore((s) => s.closeSettings)
  const userId = useStore((s) => s.userId)
  const tab = useStore((s) => s.settingsTab)
  const setTab = (t: SettingsTab) => useStore.setState({ settingsTab: t })
  if (!open || !userId) return null
  return (
    <>
      <div className="fixed inset-0 z-40 bg-slate-900/30 backdrop-blur-sm" onClick={close} />
      <aside className="fixed right-0 top-0 z-50 flex h-full w-[32rem] max-w-[94vw] flex-col rounded-l-2xl border-l border-slate-200 bg-white shadow-pop">
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <span className="text-base font-semibold tracking-tight text-slate-800">设置</span>
          <button
            aria-label="关闭设置"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            onClick={close}
          >
            <X size={16} />
          </button>
        </header>
        <div className="flex min-h-0 flex-1">
          <SettingsNav tab={tab} onSelect={setTab} />
          <div className="min-w-0 flex-1 overflow-auto p-4">
            {tab === "agent" && <AgentSettings />}
            {tab === "skills" && <SkillsPanel />}
            {tab === "memory" && (
              <MemoryPanel
                scope="user"
                hint="跨你所有 agent 的个人长期记忆;agent 在对话空闲/压缩时自动维护。"
              />
            )}
            {tab === "keys" && <KeysPanel />}
          </div>
        </div>
      </aside>
    </>
  )
}
```

- [ ] **Step 2: tsc + 全量 vitest(确认没碰坏面板测试)**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: tsc 0 错;现有测试全绿(面板测试按文本/角色定位,不受壳改动影响)。

- [ ] **Step 3: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/settings/SettingsDrawer.tsx
git commit -m "feat(frontend): settings drawer with left-rail nav

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `AgentSettings` → 分组设置行

**Files:** Modify `settings/AgentSettings.tsx`(必要时 `AgentSettings.test.tsx`)

**保留不变**:`createAgent`/`save` mutations、`inited` 首灌、`enabledToChecked/checkedToEnabled`、工具/技能 `toggle`、`invalid` 校验、内嵌 `MemoryPanel(scope=agent)`、保存提示。**只换外壳**:`SectionTitle`/`Field` + 手搓 bordered 列表 → `SettingGroup`/`SettingRow`。

- [ ] **Step 1: 重排 JSX(逻辑原样保留)**

把 `import { ... Field ... } from "../ui"` 改为引入 `SettingGroup, SettingRow`(`Field` 不再需要可移除)。`AgentEditor` 的 return 重排为分组:

- **基本组** `<SettingGroup label="基本">`:名称/模型/Provider 三个 `<SettingRow label block><Input .../></SettingRow>`(`block` 让输入整行,窄抽屉里更好用)。
- **模型行为组** `<SettingGroup label="模型行为">`:
  - `<SettingRow label="思考档位">` 包 `<Segmented .../>`(原 options 不变)。
  - `<SettingRow label="凭据" hint="空 = 用平台全局共享 Key">` 包 `<SelectMenu .../>`(原 options 不变)。
- **工具组** `<SettingGroup label="工具">`:`BUILTIN_TOOLS.map` → 每项一个 `<SettingRow label={t.name} hint={t.desc}><Switch .../></SettingRow>`(去掉原来手搓的 `border-t` 容器,分隔线由 SettingGroup 提供)。
- **指令组** `<SettingGroup label="指令(AGENTS)">`:一个 `<SettingRow label="给这个 agent 的指令 / 人设" block><Textarea .../></SettingRow>`。
- **记忆组** `<SettingGroup label="记忆(学到的)">`:`<div className="p-3"><MemoryPanel scope="agent" agentId={agentId} hint="…(原文案)" /></div>`(MemoryPanel 自带控件,放进卡里留 padding)。
- **技能组** `<SettingGroup label="启用技能">`:pool 为空显示空态行;否则 `pool.map` → `<SettingRow label={sk.name} hint={sk.description}><Switch .../></SettingRow>`。
- **保存条**:保留原 `<Button onClick={save.mutate}>` + `已保存 ✓`,外层 `border-t border-slate-100 pt-4`。

新建模式(`!agentId`)的表单同样用一个 `<SettingGroup label="新建 Agent">` 包三个 `block` 输入行 + 创建按钮。删除局部 `SectionTitle` 组件。

> 关键:`<Input>` 默认 `w-full`(见 controlCls),在 `block` 行里自然撑满;`Switch`/`Segmented`/`SelectMenu` 的 props 与原先逐字一致。

- [ ] **Step 2: 更新/核对测试**

Run: `cd frontend && npx vitest run src/components/settings/AgentSettings.test.tsx`
若失败:测试若按 `Field` 的 label 文案或 `SectionTitle` 文本定位,改为按保留的 label 文本(名称/模型/Provider/思考档位/凭据/工具/启用技能)或控件 `aria-label`/role 定位;断言 mutation 行为(填表→点击保存→`api.patchAgent` 被调)保持不变。
Expected: PASS。

- [ ] **Step 3: tsc + live 冒烟(实现者本地)**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 错(确认移除 `Field` 后无残留引用)。

- [ ] **Step 4: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/settings/AgentSettings.tsx frontend/src/components/settings/AgentSettings.test.tsx
git commit -m "feat(frontend): AgentSettings as grouped setting rows

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `SkillsPanel` / `KeysPanel` / `MemoryPanel` → 分组

**Files:** Modify `settings/SkillsPanel.tsx`, `KeysPanel.tsx`, `MemoryPanel.tsx`(必要时各自 test)

保留所有 mutation/query/state;只把「`text-sm font-semibold` 标题 + 手搓卡片」换成 `SettingGroup`/`SettingRow`,与 Agent 面板节奏统一。

- [ ] **Step 1: SkillsPanel**

- 「已安装」→ `<SettingGroup label="已安装">`:每个技能一个 `<SettingRow label={sk.name} hint={sk.description}>` 右侧放「删除」按钮(`<Button variant="ghost" size="sm">` 或保留现有红字 hover 按钮)。空态在组外显示 `text-xs text-slate-400`。
- 「从 registry 安装」→ `<SettingGroup label="从 registry 安装">` 内一个 `block` 行:`SelectMenu` + 安装 `Button`(横排,`flex items-start gap-2`)。

- [ ] **Step 2: KeysPanel**

- 「已保存的凭据」→ `<SettingGroup label="已保存的凭据">`:每条凭据一个 `<SettingRow label={c.name} hint={\`${c.masked}${c.base_url ? " · " + c.base_url : ""}\`}>` 右侧「删除」按钮。
- 「添加凭据」表单 → `<SettingGroup label="添加凭据">` 内三个 `block` 行(名称/Base URL/API Key,沿用 `Input` 与原 `hint`)+ 保存按钮(表单 `onSubmit` 逻辑不变)。底部说明文案保留。

- [ ] **Step 3: MemoryPanel**

MemoryPanel 同时被设置「记忆」tab(user)与 AgentSettings(agent)复用,**保持对外 props/行为不变**。仅微调内部:文本域 + hint + 保存/清空按钮already 紧凑,可不强改;若要统一,用 `<SettingGroup>` 包文本域为一个 `block` 行。**最小改动:仅把内部不一致的圆角/间距对齐到 SettingGroup 风格**(可选)。优先保证它在「记忆」tab 和 Agent 面板里都不破。

- [ ] **Step 4: 测试 + tsc**

Run: `cd frontend && npx vitest run src/components/settings/ && npx tsc --noEmit`
若某测试按旧标题文本(如「已安装」「添加凭据」)定位且仍保留为 `SettingGroup` 的 `label`,则不受影响;按钮(安装/删除/保存)按文本定位也不变。修正任何因结构变化失配的定位。
Expected: PASS + tsc 0 错。

- [ ] **Step 5: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/settings/SkillsPanel.tsx frontend/src/components/settings/KeysPanel.tsx frontend/src/components/settings/MemoryPanel.tsx frontend/src/components/settings/*.test.tsx
git commit -m "feat(frontend): skills/keys/memory panels as grouped rows

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `Sidebar` 壳 + 幽灵新对话行 + 图标

**Files:** Modify `Sidebar.tsx`, `Sidebar.test.tsx`

保留:`create` mutation、`agentId` 守卫禁用、`AgentList`/`SessionList`/`AccountMenu` 组合。变化:大主按钮 → 幽灵行(`Plus` 图标 + 「新对话」),容器留白略增。

- [ ] **Step 1: 改新对话按钮**

`import { Plus } from "lucide-react"`;把 `<Button>＋ 新对话</Button>` 换成:

```tsx
<button
  disabled={!agentId || create.isPending}
  title={agentId ? "" : "先选择 / 新建一个 agent"}
  onClick={() => create.mutate()}
  className="flex w-full items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
>
  <Plus size={16} className="text-slate-400" />
  新对话
</button>
```

(移除对 `Button` 的 import,若 Sidebar 不再用它。)品牌头保留 teal 渐变方块 + 字标不变。

- [ ] **Step 2: 更新测试**

Edit `frontend/src/components/Sidebar.test.tsx:27`:`getByRole("button", { name: "＋ 新对话" })` → `getByRole("button", { name: "新对话" })`(lucide 图标无文本,可达名即「新对话」)。

- [ ] **Step 3: 测试 + tsc**

Run: `cd frontend && npx vitest run src/components/Sidebar.test.tsx && npx tsc --noEmit`
Expected: PASS + 0 错。

- [ ] **Step 4: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/Sidebar.tsx frontend/src/components/Sidebar.test.tsx
git commit -m "feat(frontend): sidebar ghost new-chat row + lucide plus

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `AgentList` 重绘 + 设置图标

**Files:** Modify `AgentList.tsx`

保留:`agents` query、`setAgent`、`openSettings`、`newAgent`、空态、选中判定。变化:分节标题轻量化(保留 `Agents` 小标题 + 右侧 `Plus` 新建按钮);agent 行选中柔色(`bg-brand-50`,去掉 ring 或保留轻 ring);设置入口 emoji `⚙` → `<Settings2 size={14}>`(选中常显、其余 `group-hover` 显);新建 `＋` → `<Plus size={14}>`。

- [ ] **Step 1: 换图标 + 柔化**

`import { Plus, Settings2 } from "lucide-react"`。把分节头的 `＋` 按钮内容换 `<Plus size={14}/>`(保留 `aria-label="新建 agent"`);把每行的 `⚙` 按钮内容换 `<Settings2 size={14}/>`(保留 `aria-label={`${a.name} 设置`}`);选中行样式按 Notion 柔和微调(`bg-brand-50`,文字 `text-brand-800`/`text-brand-700`)。其余逻辑逐字保留。

- [ ] **Step 2: tsc + 相关测试**

Run: `cd frontend && npx vitest run src/components/Sidebar.test.tsx && npx tsc --noEmit`
(AgentList 无独立 test;Sidebar.test 覆盖组合渲染。)若 Sidebar.test 按 `⚙`/`＋` 文本定位则改为 `aria-label`;当前未发现此类定位。
Expected: PASS + 0 错。

- [ ] **Step 3: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/AgentList.tsx
git commit -m "feat(frontend): AgentList lucide icons + softer selection

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: `SessionList` 重绘

**Files:** Modify `SessionList.tsx`

保留:sessions/agents query、过滤当前 agent、`setSession`、空态文案、选中判定。变化:会话行与 agent 行视觉节奏统一(柔色选中 `bg-brand-50`,hover `bg-slate-100`,统一圆角 `rounded-lg`),分节标题轻量化。纯 className 调整,无逻辑变化、无图标。

- [ ] **Step 1: 调样式**

按上述把会话行/标题 className 对齐 Notion 柔和(与 AgentList 一致的选中/hover/圆角)。

- [ ] **Step 2: tsc + 测试**

Run: `cd frontend && npx vitest run src/components/Sidebar.test.tsx && npx tsc --noEmit`
Expected: PASS + 0 错。

- [ ] **Step 3: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/SessionList.tsx
git commit -m "feat(frontend): SessionList rhythm aligned to Notion-soft

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: `AccountMenu` 图标

**Files:** Modify `AccountMenu.tsx`(`AccountMenu.test.tsx` 预计无需改)

保留:user 守卫、点外面关闭、`doLogout`、`toggleFileDrawer`、`openSettings("keys")`、头像 teal 渐变。变化:菜单项 emoji → lucide,触发器尾部 `▾` → `<ChevronDown>`。文本标签(工作区文件/Provider Keys/登出/邮箱)**保持不变**(AccountMenu.test 按这些文本定位,不能改文案)。

- [ ] **Step 1: 换图标**

`import { ChevronDown, Folder, KeyRound, LogOut } from "lucide-react"`。三个菜单项左侧的 `<span>📁/🔑/⏻</span>` 换成对应 `<Folder size={15}/>` / `<KeyRound size={15}/>` / `<LogOut size={15}/>`(登出项保留 `hover:text-red-600`);触发器尾部 `▾` 换 `<ChevronDown size={14} className="shrink-0 text-slate-400"/>`。`item` 类名与文本标签不变。

- [ ] **Step 2: 测试 + tsc**

Run: `cd frontend && npx vitest run src/components/AccountMenu.test.tsx && npx tsc --noEmit`
Expected: PASS(文本定位不受图标影响)+ 0 错。

- [ ] **Step 3: 提交**

```bash
cd /Users/wuhaowen/src/llm-agent/agent-cloud
git add frontend/src/components/AccountMenu.tsx
git commit -m "feat(frontend): AccountMenu lucide icons

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: 全量回归 + 实跑验证 + 对抗审查 + 收尾

**Files:** 无(验证 + 收尾)

- [ ] **Step 1: 全量**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: tsc 0 错;vitest 全绿(新增 SettingGroup/SettingsNav 测试 + 既有测试)。

- [ ] **Step 2: 残留 emoji 扫描**

Run: `cd frontend && rg -n "📁|🔑|⏻|⚙|＋|▾" src/components/Sidebar.tsx src/components/AgentList.tsx src/components/SessionList.tsx src/components/AccountMenu.tsx src/components/settings/SettingsDrawer.tsx`
Expected: 无命中(范围内 emoji 已清;✕ 在 SettingsDrawer 已换 X;✓ 保存提示属文字反馈,保留)。

- [ ] **Step 3: 实跑验证(preview,需登录)**

起预览,登录后逐项对照 [设计 spec](docs/superpowers/specs/2026-06-10-ui-redesign-sidebar-settings-design.md)([feedback_preview_react_inputs]:React 输入用原生 setter + input 事件):
- 侧边栏:幽灵「新对话」行(无 agent 禁用)、agent/会话柔色选中、SVG 图标、账户菜单图标 + 展开。
- 设置抽屉:左侧图标导航切 4 个面板、分组设置行、宽度 32rem、✕ 关闭。
- Agent 面板:改名/模型/思考档位/凭据/工具开关/指令/记忆/技能 → 保存生效(回归功能没坏)。
- Keys/技能/记忆面板:增删/安装/保存正常。
截图留证(侧边栏 + 设置抽屉)。

- [ ] **Step 4: 对抗式代码审查**

按 [feedback_dev_workflow]:用 Opus 子 agent(`model:"opus"`)审本分支 diff(diff 内联,勿大批量写文件)。重点:可访问性(图标按钮有无可达名/aria-label、`aria-current`)、是否误改了逻辑(mutation/query/state 应零变化)、`Field` 移除后无残留引用、窄抽屉里 SettingRow 横排输入是否被挤变形、暗色/对比可读性。问题 controller 直接改 + 回归。

- [ ] **Step 5: 收尾**

按 superpowers:finishing-a-development-branch 给选项(PR / 合并 / 保留 / 丢弃)。

---

## Self-Review notes

- **Spec 覆盖**:#1 图标(Task 1/3/4/7/8/10 + Step 2 扫描)✓;#3 侧边栏(Task 7/8/9,方向 B 柔和)✓;#4 设置抽屉(Task 3/4 左导航 + Task 5/6 分组行)✓;lucide(Task 1)✓;保留 teal 渐变(品牌头/头像/Button primary 不动)✓;范围外不动(聊天/文件/登录布局未列入)✓。
- **类型一致**:`SettingsTab` 由 store 导出复用(SettingsNav/SettingsDrawer);`SettingGroup({label?,children})`、`SettingRow({label,hint?,block?,children})` 在 Task 5/6 的调用与 Task 2 定义一致;lucide 图标名(Plus/X/Bot/Blocks/Brain/KeyRound/Folder/LogOut/ChevronDown/Settings2)在 Task 1 Step 2 统一冒烟校验。
- **无占位符**:基元/导航/抽屉给完整代码;restyle 任务给目标结构 + 精确类/图标/保留逻辑 + 测试更新点,最终像素级 Tailwind 由 live-verify 收敛(已在 Architecture 声明,非 TODO)。
