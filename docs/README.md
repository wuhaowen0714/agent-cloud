# 文档索引

- **[roadmap.html](roadmap.html)** — 路线图(P1–P5 阶段、缺口与推进顺序;随特性落地持续更新)。
- **[architecture.html](architecture.html)** — **早期设计快照**(项目启动期写就):四层架构的最初蓝图。现状描述以仓库根 [README](../README.md) 为准。
- **[superpowers/specs/](superpowers/specs/)** — 每个特性的设计规格(brainstorm 后落档,按日期命名)。
- **[superpowers/plans/](superpowers/plans/)** — 与 specs 对应的逐任务实现计划(TDD 步骤级,执行过程的工作文档)。

## 设计规格一览

| 日期 | 规格 | 一句话 |
|---|---|---|
| 06-05 | [stateless-agent-cloud-design](superpowers/specs/2026-06-05-stateless-agent-cloud-design.md) | 创世设计:前端 / Backend / Worker / Sandbox 四层 + Postgres 的无状态多租户架构 |
| 06-07 | [docker-sandbox-provisioner](superpowers/specs/2026-06-07-docker-sandbox-provisioner-design.md) | docker 沙箱 provisioner:真隔离、资源限额、空闲回收、持久 `/workspace` 卷 |
| 06-07 | [file-management](superpowers/specs/2026-06-07-file-management-design.md) | 用户工作区文件管理(浏览 / 预览 / 上传 / 删除,路径越狱防护) |
| 06-07 | [frontend-chat-mvp](superpowers/specs/2026-06-07-frontend-chat-mvp-design.md) | 前端聊天 MVP:SSE 流式回合、会话 / agent 管理 |
| 06-08 | [agent-config-management-ui](superpowers/specs/2026-06-08-agent-config-management-ui-design.md) | agent 配置管理 UI(设置抽屉:模型 / 工具 / 指令 / 技能) |
| 06-08 | [auth-multitenancy](superpowers/specs/2026-06-08-auth-multitenancy-design.md) | 鉴权与多租户:JWT + httpOnly refresh 轮换,跨租户一律 404 |
| 06-08 | [reconnectable-turns](superpowers/specs/2026-06-08-reconnectable-turns-design.md) | 断线可续看:服务端回合继续跑,重连 resume 补播 + 实时 |
| 06-08 | [session-compaction](superpowers/specs/2026-06-08-session-compaction-design.md) | 会话历史压缩:旧消息折叠成增量摘要,阈值触发 |
| 06-08 | [turn-recovery-auto-retry](superpowers/specs/2026-06-08-turn-recovery-auto-retry-design.md) | 回合失败透明自愈:超窗压缩重试、瞬时错误退避重试 |
| 06-09 | [agent-memory](superpowers/specs/2026-06-09-agent-memory-design.md) | 智能体记忆:自整合单块,空闲 + 压缩前自动提炼(LLM 对账重写) |
| 06-09 | [remember-tool](superpowers/specs/2026-06-09-remember-tool-design.md) | `remember` 工具:agent 主动写长期记忆(worker 原生,不进沙箱) |
| 06-09 | [slash-commands](superpowers/specs/2026-06-09-slash-commands-design.md) | 斜杠命令面板:`/compact` `/status` `/new` `/model` `/help` + 设置导航 |
| 06-10 | [ui-redesign-sidebar-settings](superpowers/specs/2026-06-10-ui-redesign-sidebar-settings-design.md) | UI 重设计:Notion 风侧栏 + 设置左导航 + lucide 图标系统 |
| 06-10 | [model-switcher](superpowers/specs/2026-06-10-model-switcher-design.md) | 模型切换器:composer chip、预设 ∪ 在用 ∪ 自定义(后端持久化) |
| 06-10 | [agent-lifecycle](superpowers/specs/2026-06-10-agent-lifecycle-design.md) | 生命周期:注册播种默认 agent / 会话、一键新建、行内改名 / 删除 |

> 规格是"批准时的设计";个别细节会在实现与对抗审查中修订(修订一般会回写规格,以规格文末状态为准)。
