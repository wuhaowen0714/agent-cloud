# Agent / 配置管理 UI + 侧栏重设计 — 设计文档

> 日期:2026-06-08 · 关联:[[stateless-agent-cloud-design]] §5(配置/Memory/Skill scope)、[[project_frontend]]

## 1. 背景与目标

后端的可配置面已经齐全(agent 设置 / 工具 / 技能 / 指令文档都有 API),但前端只有一个简陋的内联建 agent 表单,**没有任何配置入口**;侧栏控件平铺、无层级、会话标题是 uuid 截断,观感差。

**目标**:把已建好的后端配置面**暴露成一套好看、可用的 UI**——Agent 设置(基础 + 工具 + 指令文档)+ 技能管理(池 + 每 agent 启用),并**重设计侧栏**使其分组清晰、风格统一(浅色 + teal)。

## 2. 范围

**做**:
- 后端:新增 `GET /skills/registry`(列出可安装的内置技能名)。
- 前端:**右侧"设置"抽屉**(与文件抽屉一致),分页签 **Agent | 技能**;**侧栏重设计**;store 加 `settingsOpen`;api/client 补齐配置相关方法。

**不做**(v1):`permissions` 原始编辑、上传 zip 技能(默认 `allow_uploaded_archives=false`)、`key_ref`/凭据管理、memory 管理 UI、技能市场/检索。

## 3. 后端补充

`services/backend/.../api/skills.py` 新增:

```python
@router.get("/registry", response_model=list[str])
def list_registry_skills(registry_root: Path = Depends(get_skill_registry_root)):
    """列出 registry 里可安装的技能名(目录名 + 含 SKILL.md)。"""
    if not registry_root.exists():
        return []
    return sorted(
        p.name for p in registry_root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    )
```

路由顺序无冲突(`GET /skills/registry` 与 `DELETE /skills/{id}` 方法/路径不同)。其余全部复用现有 API:
- `PATCH /agent-configs/{id}`(`AgentConfigUpdate`:name/model/provider/thinking_level/enabled_tools/…)
- `GET /context-documents?scope=agent&owner_id={agentId}` / `PUT /context-documents {scope,type,owner_id,content}`
- `GET /skills?user_id=` / `POST /skills/install {user_id,name}` / `DELETE /skills/{id}`
- `GET /agent-configs/{id}/skills` / `PUT /agent-configs/{id}/skills {skill_ids}`

## 4. 前端:API client + 类型

`types.ts` 补:
```typescript
export interface Skill { id: string; user_id: string; name: string; description: string; source: string; version: string }
export interface ContextDocument { id: string; scope: string; type: string; owner_id: string; content: string }
```
(`AgentConfig` 已含 name/model/provider/thinking_level/enabled_tools/permissions。)

`api/client.ts` 补:
```typescript
patchAgent: (id, body: Partial<Pick<AgentConfig,"name"|"model"|"provider"|"thinking_level"|"enabled_tools">>)
            => http<AgentConfig>(`/agent-configs/${id}`, { method:"PATCH", body: JSON.stringify(body) }),
listDocs:   (scope, ownerId) => http<ContextDocument[]>(`/context-documents?scope=${scope}&owner_id=${ownerId}`),
putDoc:     (scope, type, ownerId, content) =>
            http<ContextDocument>(`/context-documents`, { method:"PUT", body: JSON.stringify({scope,type,owner_id:ownerId,content}) }),
listSkills: (userId) => http<Skill[]>(`/skills?user_id=${userId}`),
listRegistry: () => http<string[]>(`/skills/registry`),
installSkill: (userId, name) => http<Skill>(`/skills/install`, { method:"POST", body: JSON.stringify({user_id:userId,name}) }),
deleteSkill: (id) => http<void>(`/skills/${id}`, { method:"DELETE" }),
getAgentSkills: (agentId) => http<Skill[]>(`/agent-configs/${agentId}/skills`),
setAgentSkills: (agentId, skillIds) => http<Skill[]>(`/agent-configs/${agentId}/skills`, { method:"PUT", body: JSON.stringify({skill_ids:skillIds}) }),
```

## 5. 前端:store

`store.ts` 加(与 `fileDrawerOpen` 同样式):
```typescript
settingsOpen: boolean
toggleSettings: () => void
```
`setUser`/`setAgent` 切换时关掉设置抽屉(`settingsOpen:false`),避免对着旧 agent 的设置。

## 6. 前端:侧栏重设计

`Sidebar.tsx` 重写为分组结构(每组一个 xs 大写 slate-400 小标题),并重做子部件样式:

```
┌─ agent-cloud ───────────────┐   字标
│ ● wuhaowen@…        切换     │   UserBar:圆点 + 截断 email + 切换
├─ AGENT ─────────────────────┤   小标题
│ [测试 · DeepSeek ▾] [⚙] [＋] │   AgentSelector:下拉 + 设置 + 新建
├─ 工作区 ────────────────────┤
│ 📁 文件                      │   FileButton
├─ 会话 ───────────────  ＋新建 │   小标题 + 新会话
│ • 排序脚本                   │   SessionList:友好标题、teal 选中、hover
│   curl 测试                  │
└─────────────────────────────┘
```

- **UserBar**:圆点(teal)+ 截断 email + "切换"(文字按钮)。
- **AgentSelector**:`<select>`(当前 agent)+ **⚙**(开设置抽屉,Agent 页)+ **＋**(`setAgent(null)` 后开设置抽屉 → Agent 页显示新建表单)。**删掉原内联三行建 agent 表单**。
- **SessionList**:标题用 `s.title ?? "会话 "+id.slice(0,6)`;选中 teal 底、未选 hover;"＋ 新会话" 放在"会话"小标题行右侧。
- 统一:`gap-3`、分组小标题、轻分隔线、teal 强调、按钮风格一致。

## 7. 前端:设置抽屉

`components/settings/SettingsDrawer.tsx`——右侧滑出(同文件抽屉:遮罩 + `translate-x` + 固定右侧),仅 `settingsOpen && userId` 时渲染。顶部:标题"设置" + ✕;下方页签 **Agent | 技能**(本地 `useState` 选中页)。

### 7.1 Agent 页(`AgentSettings.tsx`)

- **无选中 agent(agentId null)→ 新建模式**:表单 名称/模型/provider → "创建 agent"(`createAgent`)→ 成功后 `setAgent(新id)` 切到编辑模式。
- **编辑模式(选中 agent)**:
  - 字段:名称、模型、provider、思考档位(`<select>`:默认/low/medium/high,空=默认)。
  - **工具**:`bash`/`write_file`/`read_file` 三个勾选(各带说明)。初始:`agent.enabled_tools` 非空则按其勾选,空则**全勾**(空=全部,见 §9)。
  - **指令**:AGENTS 文档 `<textarea>`(进入时 `listDocs("agent",agentId)` 找 `type==="AGENTS"` 回填)。
  - **启用技能**:技能池(`listSkills`)逐项勾选,初始勾中 = `getAgentSkills(agentId)`。池为空时提示去"技能"页安装。
  - **保存**:并发 `patchAgent`(name/model/provider/thinking_level/enabled_tools)+ `putDoc("agent","AGENTS",agentId,指令)`(指令非空时)+ `setAgentSkills(agentId, 勾选ids)`;成功后失效 `["agents",userId]` 等查询,提示"已保存"。

### 7.2 技能 页(`SkillsPanel.tsx`)

- **已安装池**:`listSkills(userId)` 列表,每项 名称 + 描述 + **删除**(`deleteSkill` → 失效)。
- **安装**:`listRegistry()` 下拉选一个 registry 技能 → "安装"(`installSkill(userId, name)` → 失效池查询)。已安装的从下拉过滤掉。
- 删除/安装后失效 `["skills",userId]` + `["agentSkills",*]`(启用集可能受影响)。

## 8. 数据流

1. 侧栏 ⚙ → `toggleSettings()` → 抽屉开,Agent 页加载当前 agent 字段 + 文档 + 技能勾选。
2. 改字段 → 保存 → PATCH + PUT 文档 + PUT 技能 → 失效查询 → 侧栏下拉名称/模型即时更新。
3. ＋ → `setAgent(null)` + 开抽屉 → Agent 页新建表单 → 创建 → 自动切到该 agent 编辑。
4. 技能页 安装/删除 → 失效池 → Agent 页的技能勾选随之更新。

## 9. enabled_tools 语义(注明)

worker 端 `filtered_tool_specs`:`enabled_tools` 为空 = **暴露全部内置工具**。故 UI 约定:空 → 全勾显示;保存勾选子集即生效。**全勾时保存 `[]`(规范化为"全部"),勾子集时保存该子集**。(0 勾选属异常,等同空=全部,不特殊处理。)

## 10. 测试

- **后端**:`GET /skills/registry` → 含 `example-greeting`(测试加临时 registry 或断言含已知名)。
- **前端纯逻辑**:工具勾选 ↔ enabled_tools 的初始化/规范化(空=全勾、全勾=保存[]、子集=保存子集)抽成纯函数 `toolsToEnabled`/`enabledToTools` 单测。
- **前端组件**:`AgentSettings` 渲染字段 + 工具勾选 + 保存触发 mutation(mock api);`SkillsPanel` 列表 + 安装/删除触发 mutation;`SettingsDrawer` 页签切换;侧栏 ⚙/＋ 触发 `toggleSettings`/`setAgent(null)`。
- **实景**:连运行栈,改 agent 模型/工具/指令并保存 → 重开确认持久;装一个 registry 技能 + 在 agent 勾启用 → 截图。

## 11. 后续演进

- `GET /tools` 端点(替代前端硬编码工具表)。
- permissions 结构化编辑;memory 管理;上传 zip 技能(配 `allow_uploaded_archives`);技能市场/检索。
- 多 agent 文档类型(SOUL/IDENTITY/TOOLS…)的编辑。
