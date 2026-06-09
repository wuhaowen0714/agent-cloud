# 前端 UI 重设计(侧边栏 + 设置抽屉)设计

**日期:** 2026-06-10
**状态:** 设计已批准,待写实现计划

## 目标

修掉当前 UI 最「土」的两块观感问题(用户优先级:侧边栏、设置抽屉),并建立一套统一的线性图标系统。审美对标 Linear / Notion / Vercel,落到「Notion 柔和」语言:柔色填充、圆润、留白、低对比标签。

用户明确的痛点(编号沿用 brainstorm):
1. **emoji 当图标**(📁 🔑 ⏻ ⚙ ＋ ▾ ✕)→ 全部换成线性 SVG 图标。
3. **侧边栏层级/密度/分组**生硬 → 重排为 Notion 柔和。
4. **设置抽屉像管理后台** → 左侧竖排图标导航 + 右侧分组设置行。

## 非目标(YAGNI / 范围外)

- **不动**聊天区(MessageList / Bubble / TurnBlocks / ThinkingPanel / ToolCallCard / Markdown / Composer / slash)、文件抽屉、登录页的**布局**。
- 不改任何数据流 / store / api / 后端;纯前端表现层。
- 不加暗色模式(本轮不做)。
- **保留** teal 渐变(brainstorm #2 未被选中)。
- 不新增设置项 / 功能,只重排与重绘。
- 抽屉外壳抽象(`Drawer`)**可选**,不强求(Files 抽屉不在范围内)。

## 审美语言:Notion 柔和

- **选中态**:柔色填充(`bg-brand-50` / `bg-brand-100`,brand 即 teal)+ 圆角,不用重边框或高饱和。
- **留白**:分节之间、行内控件留白更舒展;触达面积更大(行 padding 提升)。
- **标签**:分节标题低对比(`text-slate-400`),字号小;减少 ALL-CAPS 的生硬感(可用 sentence case 或更轻的 uppercase)。
- **圆角**:统一 `rounded-lg`/`rounded-xl`。
- **图标**:全部线性 SVG(见下),默认 16px、`stroke-width≈1.6`、`text-slate-400~500`,选中/悬停加深。
- **保留**:teal 渐变(logo 方块、账户头像)。

## 图标系统(lucide-react)

引入 `lucide-react`(MIT、按需 tree-shake)。直接按需 import,不做包装层;统一约定:侧栏/菜单图标 `size={16}`,设置左导航 `size={18}`,`className` 控制颜色。

**动作 → 图标映射**(供实现对照):

| 用途 | lucide | 取代 |
|---|---|---|
| 新建 / 新对话 | `Plus` | ＋ |
| agent 设置 | `Settings2` | ⚙ |
| 下拉指示 | `ChevronDown` | ▾ |
| 工作区文件 | `Folder` | 📁 |
| Provider Keys | `KeyRound` | 🔑 |
| 登出 | `LogOut` | ⏻ |
| 关闭 | `X` | ✕ |
| 设置·Agent tab | `Bot` | — |
| 设置·技能 tab | `Blocks` | — |
| 设置·记忆 tab | `Brain` | — |
| 设置·Keys tab | `KeyRound` | — |

> 范围内出现的所有 emoji 字形图标都替换;范围外组件(slash/files/chat)本轮不动。

## 侧边栏重设计(方向 B · Notion 柔和)

整体结构不变(品牌头 → 新对话 → Agents → 当前 agent 的对话 → 账户),只重排层级、换图标、柔化。**不动数据逻辑**(agent 列表、会话过滤、新建会话的 mutation 全保留)。

- **[Sidebar.tsx](frontend/src/components/Sidebar.tsx)**:容器留白略增;品牌头保留 teal 渐变方块 + 字标。
- **新对话**:从大主按钮 → **幽灵行**(`Plus` 图标 + 「新对话」文本,软边框 `border` + `rounded-xl`,hover 柔色填充)。无 agent 时禁用态保留。
- **[AgentList.tsx](frontend/src/components/AgentList.tsx)**:分节标题轻量化;agent 行 hover/选中用柔色填充(选中 `bg-brand-50`);设置入口用 `Settings2`(选中常显、其余 hover 显)。
- **[SessionList.tsx](frontend/src/components/SessionList.tsx)**:会话行柔化(选中柔色填充),与 agent 行视觉节奏统一;空态文案保留。
- **[AccountMenu.tsx](frontend/src/components/AccountMenu.tsx)**:头像保留 teal 渐变;菜单项图标 `Folder`/`KeyRound`/`LogOut`,触发器尾部 `ChevronDown`;弹层风格沿用现有 `shadow-pop` 浮层。

## 设置抽屉重设计(左导航 + 分组行,保持抽屉宽度)

**[SettingsDrawer.tsx](frontend/src/components/settings/SettingsDrawer.tsx)**:从「顶部下划线 tab」改为「**左侧竖排图标导航 + 右侧内容**」,**仍是右侧抽屉**(不改居中模态)。宽度从 `w-[30rem]` 微调到 `w-[32rem]` 以容纳 rail。

- **头部**:标题「设置」+ 右上 `X` 关闭(lucide)。
- **左导航(新组件 `SettingsNav`)**:竖排 4 项 `{Agent(Bot) / 技能(Blocks) / 记忆(Brain) / Keys(KeyRound)}`;选中柔色填充(`bg-brand-50 text-brand-700`);宽约 `w-36`,`border-r`。
- **右内容**:`flex-1 overflow-auto`,渲染对应面板。

四个面板的表单 → **分组设置行**(新基元):

- **`SettingGroup`**(`ui/SettingGroup.tsx`):可选低对比分节标题 + 软边框圆角容器(`border border-slate-100 rounded-xl`),内含若干行(行间细分隔线)。
- **`SettingRow`**(`ui/SettingRow.tsx`):`label`(+ 可选 `hint` 副文案)在左、控件在右的对齐行;`block` 变体用于宽控件(工具勾选 chips、文本域)整行铺开。复用现有 `Input / Switch / Segmented / SelectMenu / Button`。

面板改造(逻辑不变,只换外壳):
- **[AgentSettings.tsx](frontend/src/components/settings/AgentSettings.tsx)**:名称/模型/Provider/思考强度/Key 引用 → `SettingRow`;启用工具 → `block` 行内的 chip 组(沿用现有勾选逻辑 `enabledToChecked/checkedToEnabled`);新建 agent 表单同样用分组行。
- **[SkillsPanel.tsx](frontend/src/components/settings/SkillsPanel.tsx)** / **[MemoryPanel.tsx](frontend/src/components/settings/MemoryPanel.tsx)** / **[KeysPanel.tsx](frontend/src/components/settings/KeysPanel.tsx)**:各自内容包进 `SettingGroup`/`SettingRow`,与 Agent 面板节奏统一。

## 受影响文件清单

**新增**
- `frontend/src/components/ui/SettingGroup.tsx`
- `frontend/src/components/ui/SettingRow.tsx`
- `frontend/src/components/settings/SettingsNav.tsx`

**修改**
- `frontend/package.json`(+ `lucide-react`)
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/components/AgentList.tsx`
- `frontend/src/components/SessionList.tsx`
- `frontend/src/components/AccountMenu.tsx`
- `frontend/src/components/settings/SettingsDrawer.tsx`
- `frontend/src/components/settings/AgentSettings.tsx`
- `frontend/src/components/settings/SkillsPanel.tsx`
- `frontend/src/components/settings/MemoryPanel.tsx`
- `frontend/src/components/settings/KeysPanel.tsx`
- `frontend/src/components/ui/index.ts`(导出新基元)
- 对应测试:`Sidebar.test.tsx` / `AccountMenu.test.tsx` / `AgentSettings.test.tsx` / `SkillsPanel.test.tsx` / `KeysPanel.test.tsx` / `MemoryPanel.test.tsx` 同步更新

## 测试

- 沿用 vitest + @testing-library。
- 受影响组件测试**改为按行为断言**(按钮存在、点击触发 action、选中态切换),不绑定具体 emoji 字符或脆弱 DOM 结构。
- 图标用 lucide:必要处给 `aria-label` 或可访问名,测试用 role/label 定位(替代原来按 emoji 文本定位)。
- 验收:`tsc` 干净 + 全量 vitest 绿;预览实跑(需登录)逐屏对照本设计。

## bug 处理

用户未点名具体 bug;重写这两块时一并扫除明显问题。若实现中发现/用户补充某个具体 bug,单列任务修。
