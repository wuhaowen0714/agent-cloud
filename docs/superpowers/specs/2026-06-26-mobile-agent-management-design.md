# Flutter App Agent 管理(创建 + 设置)设计

**日期**: 2026-06-26
**目标**: 为 `apps/mobile` 补齐「创建 agent」与「设置 agent」功能,与 web frontend 对齐。

## 背景与现状

### web 的 agent 模型(刻意极简)
`AgentConfig` 只有 `name` + `enabled_tools`(+ `permissions`,无 UI 编辑)。其余配置分离存储:
- **模型 / provider / 凭据** → session 级(不在 agent 上)。
- **人设 / 指令** → `ContextDocument`(scope=agent, type=AGENTS)。
- **专属记忆** → `MemoryBlock`(scope=agent,AI 自动维护 + 用户可手改)。
- **技能** → agent↔skill 多对多关联。

### web 的创建 / 设置交互
- 创建:左栏一键直创(默认名 `Agent N`)。
- 设置分三处:设置抽屉表单(名称/指令/记忆)、顶栏弹层(工具/技能即点即存)、头部菜单(删除)。

### app 现状
- **已有**:agent 列表 / 切换(home agent 栏)、删除(长按)、工具开关(`tools_page`)、技能开关(`skills_toggle_page`)、`AgentConfig` 模型(id/name/enabledTools)。
- **缺**:创建 agent、重命名、人设(AGENTS)、agent 专属记忆。
- 空态写死「在 web 端创建一个智能体后即可开始」。

### 后端
全部端点现成,**零改动**:
- `POST /agent-configs {name}`、`PATCH /agent-configs/{id} {name?,enabled_tools?}`、`DELETE /agent-configs/{id}`。
- `GET/PUT /context-documents`(AGENTS 人设)。
- `GET/PUT/DELETE /memory`(scope=agent 记忆)。

## 设计

核心思路:移动端把 web 分散三处的配置**聚合成一页**(Agent 设置页),符合手机单页设置习惯。决策已定:**完整对标 web(含 agent 专属记忆)** + **创建走弹窗填名**。

### 1. 创建 agent
- **入口**:home 顶部 agent 切换栏末尾加 `+` chip。
- **交互**:点 `+` → 弹窗输入框填名(复用 `home_page` 现有重命名 dialog 模式)→ 确认 → `POST /agent-configs {name}` → 乐观插入列表 + 切到新 agent → 跳转 Agent 设置页。
- 空态文案从「在 web 端创建」改为可点的「创建第一个 Agent」。

### 2. Agent 设置页(`/agent/:aid/settings`)
单页分组列表(对标 app `settings_page` 的 `_section` 卡片分组模式):

| 区块 | 内容 | 端点 |
|---|---|---|
| 名称 | 行内可编辑 | `PATCH /agent-configs/{id} {name}` |
| 人设 / 指令 | 多行 textarea + 保存 | `GET/PUT /context-documents`(scope=agent, type=AGENTS) |
| 工具 | 导航行 → 已有 `tools_page` | (已有) |
| 技能 | 导航行 → 已有 skills 页 | (已有) |
| 记忆 | 导航行 → 新 agent 记忆页 | `/agent/:aid/memory` |
| 删除 | danger 行,二次确认 dialog | `DELETE /agent-configs/{id}`(复用现有 + 409 busy 处理) |

### 3. Agent 记忆页(`/agent/:aid/memory`)
对标 web MemoryPanel(scope=agent):多行 textarea + 保存 / 清空。
- `GET /memory?scope=agent&agent_id=`、`PUT /memory {scope,content,agent_id}`、`DELETE /memory?scope=agent&agent_id=`。

### 4. 入口
- **创建**:home agent 栏末尾 `+` chip。
- **设置**:长按 agent chip 弹出底部菜单(app 现有长按已能删除),加「设置」项 → Agent 设置页。

### 5. 数据模型
- `AgentConfig` 补 `permissions`(`Map<String,dynamic>`)字段,与后端 `AgentConfigRead` 对齐(fromJson 完整性;创建/重命名本身不需要它)。
- 新增轻量模型承载 AGENTS 文档响应与 MemoryBlock(scope/content/version)。

### 6. 架构(照 app 现有四层模式)
- **Repository**:agent 相关方法集中到 agent repository(`createAgent` / `renameAgent` / `getAgentsDoc` / `putAgentsDoc` / `getAgentMemory` / `putAgentMemory` / `clearAgentMemory`)。照 `sessions_repository` 的 `?` null-aware PATCH 与箭头返回风格,不 try/catch(异常上抛,调用方 catch)。
- **State**:复用现有 `agentsProvider`;在 agent 的 AsyncNotifier(或现有 controller)加 `createAgent`/`renameAgent`,乐观更新或 `ref.invalidate(agentsProvider)`,与现有 `deleteAgent` 对称。
- **路由**:`app_router` 加 `/agent/:aid/settings` 与 `/agent/:aid/memory`(带参 builder,照现有 `/agent/:aid/tools` 写法)。
- **页面**:`features/agent/` 加 `agent_settings_page.dart`、`agent_memory_page.dart`。
- **UI**:全程 `AppTheme.*` teal token(禁散落 `Colors.*`),复用卡片容器 / 行内编辑 / 多行输入 / 导航行(ListTile + chevron)/ 删除确认 dialog / 创建填名 dialog 模式。

### 7. 测试
照 app 现有 widget test 模式(`flutter test`):
- Agent 设置页:各区块渲染、名称编辑、AGENTS 保存、三个导航行跳转、删除二次确认。
- 创建:`+` chip → 填名 dialog → 创建 → 跳转设置页。
- 记忆页:加载 / 保存 / 清空。

## 非目标(YAGNI)
- **模型 / provider / 凭据选择**:web 上是 session 级,app 已有会话级 `model_picker`,不在 agent 设置里重复。
- **技能库管理 / Provider Keys 增删**:app 已有独立设置页(`/settings/skills`、`/settings/credentials`),不重复进 agent 页。
- **permissions 编辑 UI**:web 也没有,仅解析字段保完整性。

## 文件清单
**改**:
- `apps/mobile/lib/models/agent_config.dart`(+permissions)
- agent repository(+创建/重命名/AGENTS 文档/记忆 方法)
- agent controller / provider(+create/rename)
- `apps/mobile/lib/core/router/app_router.dart`(+2 路由)
- `apps/mobile/lib/features/home/home_page.dart`(+`+` chip 创建入口 + 长按菜单「设置」+ 空态可点)

**新建**:
- `apps/mobile/lib/features/agent/agent_settings_page.dart`
- `apps/mobile/lib/features/agent/agent_memory_page.dart`
- 可能新增 `apps/mobile/lib/models/memory_block.dart` 与 context-document 轻量模型

**后端**:零改动。
