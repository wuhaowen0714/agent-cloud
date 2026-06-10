# TopBar 工具/技能开关 + 内置技能开箱即用 设计

**日期:** 2026-06-10
**状态:** 设计已批准

## 目标

1. TopBar 加「工具」「技能」两个按钮:点击弹 popover,可见全部 tool/skill 的启用状态并即点即存地开关(per-agent,作用于面包屑当前 agent)。
2. 内置技能开箱即用:registry 只留 `skill-creator`(删 `example-greeting`),自动安装、对 agent 默认启用;砍掉 SkillsPanel 的手动安装界面。

## 设计

### 1. TopBar 开关入口(前端)

- **按钮**:TopBar 右侧、Folder 左边,`Wrench`(工具)+ `Sparkles`(技能),lucide 16px,样式同既有 Folder 按钮;无选中 agent 时 disabled(title 提示「先选择 agent」)。
- **popover**:`createPortal` 到 body + fixed 定位(沿用 RowMenu 模式,规避 TopBar `backdrop-blur` 的 containing-block 陷阱);Esc / 点外关闭;一次只开一个。
- **工具 popover**(`ToolsMenu`):`BUILTIN_TOOLS`(agentConfig.ts)逐行 name + desc + `Switch`;勾选态 = `enabledToChecked(agent.enabled_tools)`(空=全部语义沿用);切换 → `checkedToEnabled` 规范化 → `api.updateAgent(PATCH enabled_tools)`,成功后 invalidate `["agents"]`(乐观更新:本地先翻,失败回滚)。
- **技能 popover**(`SkillsMenu`):列表 = `GET /skills`(全部已安装);checked = skill.id ∈ `GET /agent-configs/{id}/skills` 启用集;切换 → 集合增删 → `PUT /agent-configs/{id}/skills`(全量替换),invalidate `["agentSkills", agentId]`;空态「技能池为空」(内置 ensure 后正常不会出现)。
- **client.ts**:补 `listAgentSkills(agentId)`(目前 AgentSettings 内联取数,提为共享函数,二者共用 query key `["agentSkills", agentId]`)。
- **一致性**:TopBar 即点即存 vs 设置页 stage-then-save,最后写入者胜(与现状语义一致,不做并发合并)。

### 2. 内置技能开箱即用(后端为主)

- **registry 清理**:删除 `services/backend/src/agent_cloud_backend/skill_registry/example-greeting/` 目录;受影响测试改用 `skill-creator` 或临时 registry fixture。
- **幂等 ensure**:`ensure_builtin_skills(user_id, ...)`——对 registry 中每个含 SKILL.md 的目录,若用户未安装同名技能则 `install_skill_from_dir(source="registry")`;无缺失时仅一次目录扫描 + 名字集合比对,零写入。挂载点:
  - `GET /skills`(覆盖存量用户:任何 UI 加载即收敛;GET 带幂等副作用,注释明示取舍);
  - 注册流程(保证种子 main agent 启用时技能已存在)。
- **默认启用**:
  - 注册:种子 `main` agent 后,对其启用全部刚 ensure 的 registry 技能(同一事务);
  - `POST /agent-configs`:创建后对新 agent 启用用户当前已装的全部 `source=="registry"` 技能;
  - **存量 agent 不回填**(用户在 TopBar 一键开,不做迁移)。
- **SkillsPanel 简化**:删「从 registry 安装」整段(SelectMenu + 安装按钮 + registry query);已安装列表保留;`source === "registry"` 的行**不显示删除按钮**(内置不可删,否则无入口装回),upload/workspace 来源仍可删。
- **client.ts**:删 `listRegistry` / `installSkill`(仅该面板使用);后端 `GET /skills/registry` 与 `POST /skills/install` 端点保留(API 面不破坏,前端不再调用)。

## 非目标(YAGNI)

- 不做存量 agent 的启用回填迁移;不做工具/技能搜索过滤(数量个位数);不做启用状态的多端实时同步(invalidate 足够);不改 worker 过滤逻辑与「空 enabled_tools = 全部」语义;不删后端 registry 安装端点。

## 测试

- **后端**:ensure 幂等(两次调用一次安装);GET /skills 触发补装;注册后 main agent 启用集含 skill-creator;POST /agent-configs 新 agent 默认启用;example-greeting 移除后既有 skills 测试改造不回归;内置技能 DELETE 行为不变(后端仍允许,前端不暴露)。
- **前端**:ToolsMenu 勾选态(空=全勾)、切换 PATCH 规范化([] 当全勾)、无 agent 禁用;SkillsMenu 列表/切换 PUT 集合;TopBar 两按钮渲染与 popover 开合;SkillsPanel 无安装段、registry 行无删除按钮、upload 行有。
