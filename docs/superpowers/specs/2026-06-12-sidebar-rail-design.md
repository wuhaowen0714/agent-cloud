# 侧栏重设计:Agent rail — 设计

**日期**:2026-06-12
**目标**:重组侧栏信息架构,解决"agent 与会话主从倒置、双 + 按钮同权重、agent 行身兼三职、双高亮、动作结果分离"五个问题。纯前端,后端零改动。

## 诊断(现状问题)

1. **主从倒置**:会话(高频)压在侧栏下半段,agent(低频配置)占黄金视区,agent 越多会话区越小。
2. **动作与结果分离**:「+ 新对话」在顶部,新会话出现在底部列表,中间隔整个 Agents 区。
3. **双 + 按钮同权重**:「新对话」与「新建 Agent」同形态幽灵行,语义却是高频 vs 偶发。
4. **agent 行身兼三职**:归属指示 + 会话过滤器(因果不可见)+ 配置入口(⚙/…)。
5. **双高亮**:agent 行与会话行同时 teal 高亮,真正的工作焦点只有会话一个。

## 选型结论

**C · Agent rail(Slack/Discord 范式)**,用户评审采纳:最左窄头像栏专管"切谁",主面板整栏给"和他聊什么"。理由:本产品的 agent 带各自工具/技能/记忆,是有人格的一等实体(非 ChatGPT 式模型下拉),且用户并行使用多个 agent。
放弃:A 会话为中心(切 agent 多一步,弱化 agent 身份)、B 分组树(agent/会话增多后树过长)。

## 布局

侧栏总宽 `w-80`(320px)= **rail `w-[46px]`** + **面板 flex-1**。rail 底色 `bg-slate-50`(比面板深一档),`border-r` 分隔;面板沿用 `bg-white/80 p-3`。原品牌字标行移除。

## Rail 规格(只管"切谁",无任何管理操作)

自上而下:
- **品牌方块**:30px 圆角方块(沿用现有渐变 A),hover 自绘 tooltip「Agent Cloud」。不可点。下方一条短分隔线。
- **agent 头像列**:每个 agent 一个 30px 圆形头像,纵向排列;agent 多时此段 `overflow-y-auto`(隐藏滚动条)。
  - **缩写算法**:名字匹配 `/^([A-Za-z])[A-Za-z]*\s*(\d+)$/` → 首字母大写+数字(`Agent 1`→`A1`);否则取首字符大写(`hello`→`H`,中文取首字)。
  - **配色**:按名字哈希(charCode 求和取模)从 6 色板取 `bg-*-100 text-*-700`:teal、violet、sky、amber、rose、emerald。
  - **选中态**:`ring-2 ring-brand-500 ring-offset-1`(全侧栏 agent 维度唯一选中标识);未选中 hover 加 `ring-slate-300`。
  - **tooltip**:hover 右侧弹出(`left-full ml-2`),内容「名字 · 模型」;样式沿用 MessageActions 的自绘 tooltip 约定(深底白字 11px,hover 300ms 即显),在 AgentRail 内部实现,不抽公共组件(第三处使用时再抽)。
  - 点击 = `setAgent(id)`(沿用现有 store 语义:清 sessionId,触发自动落位)。
- **新建 Agent**:`mt-auto` 后第一个固定位,30px 虚线圆 +。点击 = 现有 create 流程(`nextAgentName` 默认名 + `DEFAULT_MODEL`)→ 成功后 `setAgent(新id)` 且**面板头部进入改名态**(见下)。
- **账户**:rail 最底,AccountMenu 触发器收成 28px 圆头像(邮箱首字母,现有渐变样式);菜单改为**向右上弹出**(`absolute left-full bottom-0 ml-2 w-52`),菜单顶部新增一行只读邮箱(原本显示在触发器上,收起后需在菜单内可见),其余项(Provider Keys / 登出)不变。

## 面板规格(只管"和他聊什么")

自上而下:
- **agent 头部**:名字(`text-sm font-semibold truncate`)+ 模型小字(`text-xs text-slate-400`);行 hover 出现 ⚙(`openSettings("agent")`)与 …(RowMenu:重命名/删除,沿用现有 AgentList 的菜单与二次确认逻辑,删除连带会话由后端保证)。**改名态**:名字变行内 input(autoFocus、Enter/blur 提交、Esc 取消,复用现有行内改名模式);新建 agent 后自动进入此态。
- **新对话主按钮**:满宽 `bg-brand-50 text-brand-700 hover:bg-brand-100 rounded-xl py-2 text-sm font-medium` + Plus 图标——全侧栏唯一的强调动作(从幽灵样式升级)。逻辑沿用现有 create mutation(无 agent 时禁用)。
- **会话列表**(占剩余高度,`overflow-y-auto`):
  - 仅当前 agent 的会话;**按 `last_active_at` 降序**;按时间分组,组标签:今天 / 昨天 / 前 7 天 / 前 30 天 / 更早(`text-[11px] text-slate-400`)。
  - 分组函数 `timeGroupLabel(iso, now = new Date())` 加在 `time.ts`(与 `fmtTime` 同档:按本地日历日比较,昨天=本地昨日,前 7 天=2~7 个本地日前,前 30 天=8~30,更早=其余)。
  - 行:标题截断(`title ?? 会话 {id前6}`,沿用),hover `bg-slate-50` + 尾部 … 菜单(重命名/删除,沿用现有 RowMenu 与 409 处理);选中 `bg-brand-50 text-brand-700`。
  - 原「{Agent} 的对话」区头删除(rail + 面板头部已表达归属)。
- **空状态**:该 agent 无会话 → 列表区居中 `text-sm text-slate-400`「还没有对话」(顶部主按钮即 CTA);无任何 agent(注册有播种,属边缘)→ 面板整体居中「在左栏 + 新建一个 Agent」。

## 行为与状态

- **类型补齐**:`types.ts` 的 `Session` 增加 `last_active_at: string`(后端 `SessionRead` 已返回,纯前端类型缺失)。
- **自动落位**:切 agent 后无选中会话 → 选该 agent **`last_active_at` 最新**的一条(替换现状"created_at 序列表末尾");agent 自愈逻辑(localStorage 残留指向已删 agent → 落回第一个)原样保留。
- store、localStorage 持久化、composer 模型 chip、TopBar、压缩/composerDraft 等一切不动。
- 排序在前端做(后端 list 仍按 created_at 升序返回,不改)。

## 错误处理

全部沿用现状:删除会话 409(回合进行中)由 RowMenu 原位提示;删除 agent 409(agent busy)同;新建失败走 mutation 错误态(按钮恢复可点)。无新增错误面。

## 测试

- `time.test.ts`:`timeGroupLabel` 各档位(含跨月/跨年、TZ 钉 Asia/Shanghai 与既有 fmtTime 测试同模式)。
- `AgentRail.test.tsx`(新):渲染头像与缩写/配色稳定性、点击切换 `setAgent`、选中 ring、+ 创建并选中、tooltip 文案存在。
- 面板头部:改名提交/Esc、⚙ 打开设置、删除菜单存在(迁移现有 AgentList 测试断言)。
- `SessionList.test.tsx`:分组渲染顺序(降序 + 组标签)、空状态、行菜单沿用断言迁移。
- `Sidebar` 自动落位:切 agent 选 last_active_at 最新(改造现有效应测试或新增)。
- 全量 `npm run lint`(tsc -b)+ `npm test` 回归。

## 范围外(YAGNI)

会话搜索、未读/运行中指示点、agent 拖拽排序、侧栏折叠、rail 右键菜单、公共 Tooltip 组件抽取、TopBar 面包屑改动。

## 改动面

- 重组:`frontend/src/components/Sidebar.tsx`
- 新建:`frontend/src/components/AgentRail.tsx`(替代 `AgentList.tsx`,后者删除)
- 修改:`frontend/src/components/SessionList.tsx`(去区头、分组、排序)、`frontend/src/components/AccountMenu.tsx`(圆头像触发器 + 右上弹出 + 菜单内邮箱行)、`frontend/src/types.ts`(Session.last_active_at)、`frontend/src/time.ts`(timeGroupLabel)
- 测试:迁移 `AgentList` 相关用例 → `AgentRail`/面板头部;`SessionList`、`time` 用例扩充。

## 工作流

worktree(已建 `worktree-feat-sidebar-rail`)→ 本 spec 用户评审 → writing-plans → controller 直接 TDD 实现 → 全量回归 → Fable 5 对抗审查 → PR。
