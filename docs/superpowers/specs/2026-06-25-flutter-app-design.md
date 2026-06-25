# Flutter App 设计 (MVP)

## 概述

为 agent-cloud 做一个 Flutter 移动 App,对接现有后端(HTTPS + token 认证 + 全部 API 均已就绪)。
本仓库此前无任何 Flutter 工程,从零开始,工程位于 `apps/mobile/`。

**MVP 范围**:核心聊天闭环 + 多模态发图 + 设置/模型选择 + 在线自动更新。
- 登录 / 注册
- 会话列表(多 agent,切换 / 新建 / 删除)
- 聊天:历史重建 + 回合流实时渲染(思考 / 文本 / 工具 / 子 agent 折叠卡)+ 文本输入 + 发图
- 设置:模型选择、登出
- 在线自动更新(自建 OTA:查版本 → 下载 APK → 安装;**支持强制更新**)

**非 MVP(后续迭代)**:文件、终端、技能管理、斜杠命令、定时任务、通知、凭据(BYO-Key)、上下文文档。

**目标平台**:先 Android(iOS 后补;Flutter 一套代码两端出)。

## 技术栈

| 层 | 选型 |
|---|---|
| 状态管理 | Riverpod |
| 网络 + 认证 | dio + 拦截器(自动 Bearer;401 自动 refresh 重试) |
| 回合流 SSE | http/dio streamed response + 自解析(SSE-over-POST) |
| Token 存储 | flutter_secure_storage(Keychain / Keystore) |
| 路由 | go_router |
| UI | Material 3 + 自定义 teal 主题(对标 web 浅色);flutter_markdown(文本块);image_picker(发图) |
| 自动更新 | ota_update 包(或 dio 下载 + install_plugin)+ package_info_plus(取当前版本):查版本 → 下 APK → 调起系统安装 |

## 工程结构(feature-first)

```
apps/mobile/
  lib/
    core/
      api/         dio client + 拦截器
      sse/         回合流 streamed 解析
      storage/     secure_storage 封装
      theme/       Material 3 + teal
      router/      go_router 配置
      update/      OTA:版本检查 + APK 下载 + 安装(支持强制更新)
    models/        User / Session / AgentConfig / Message / Block / TurnEvent
    features/
      auth/        login/register 页 + authProvider + authRepository
      sessions/    会话列表 + sessionsProvider + sessionsRepository
      chat/        聊天页 + chatProvider + chatRepository + blocks 逻辑
      settings/    设置页 + settingsProvider
    main.dart
  test/            单元 + widget 测试
  pubspec.yaml
```

## 数据模型(对标 web `types.ts`)

- **User**: `{id, email}`
- **AgentConfig**: `{id, name, enabled_tools, ...}`
- **Session**: `{id, agent_config_id, model, title, last_active_at, ...}`
- **Message**: `{id, seq, role: user|assistant|tool, content: MessageContent, created_at}`
- **MessageContent**: `{text, tool_calls: [ToolCall], tool_results: [ToolResult], parent_call_id?}`
- **ToolCall**: `{id, name, arguments}` / **ToolResult**: `{call_id, content, is_error}`
- **TurnEvent**(SSE):`text_delta` / `thinking_delta` / `tool_call_start` / `tool_call_progress` / `tool_result` / `turn_done` / `error` / `reset` / `subagent_started` / `subagent_done`(各带可选 `subagent_id`)
- **Block**(展示):`thinking` / `text` / `tool`(含 result、progress)/ `subagent`(id、description、prompt、blocks[]、running、ok)

## 核心数据流

### 认证
1. login/register → 响应体 `{access_token, refresh_token, user}` → access+refresh 存 secure_storage。
2. dio 请求拦截器:每请求加 `Authorization: Bearer <access>`。
3. dio 响应拦截器:遇 401 → `POST /auth/refresh` body `{refresh_token}` → 拿新 access+refresh → **更新存储** → 重试原请求。refresh 也 401 → 清存储 → 跳登录。
4. logout → `POST /auth/logout` body `{refresh_token}` → 清存储。

### 回合流(聊天核心)
1. 发消息 → `POST /sessions/{id}/turn/stream` body `{content, images}` → streamed response。
2. 逐行读 → 解析 SSE(`data: {json}\n\n`)→ 得 TurnEvent。
3. 喂 chatProvider 的 `applyEvent(blocks, event)` → blocks 增量更新 → UI(Riverpod watch)实时重绘。
4. 事件路由(对标 web ChatView feed):
   - `subagent_started` → `startSubagent`(建折叠卡,带 prompt)
   - `subagent_done` → `finishSubagent`
   - 带 `subagent_id` 的子事件 → `appendToSubagent`(进折叠卡)
   - `turn_done` → 标记完成 + 刷新历史
   - 其它(顶层)→ `applyEvent`(**注意**:`task` 的 `tool_call_start` 要拦截,由 subagent 卡承载、防顶层重复——见 web C1 修复)

### 历史重建
- 进会话 → `GET /sessions/{id}/messages` → `messagesToTurns(messages)` → turns/blocks。
- 含 `parent_call_id` 的子消息 → 按 parent_call_id 递归重建进对应 subagent 卡(对标 web 子 agent 过程持久化改造)。

## 回合块渲染(移植 web `blocks.ts` → Dart)

web 的 `blocks.ts` + `types.ts` 是聊天心脏,Dart 端逐函数移植 + 单测对齐:
- `applyEvent(blocks, event)`:顶层与子内部共用;thinking/text appendDelta、tool appendToolCall/attachToolResult、**task tool_call_start 拦截**。
- `startSubagent` / `appendToSubagent` / `finishSubagent`:子 agent 折叠卡。
- `messagesToTurns(messages)`:历史 → turns;`rebuildBlocks` 递归(parent_call_id 子重建,旧数据无子消息→回退结果文本)。
- UI:`TurnBlocks` 渲染器(thinking 面板 / markdown 文本 / 工具卡 / subagent 折叠卡,运行展开、完成折叠成一行)。

## API 端点(MVP 用)

- 认证:`POST /auth/{register,login,refresh,logout}`;`GET /auth/me`
- Agent:`GET /agent-configs`
- 会话:`GET/POST /sessions`;`DELETE /sessions/{id}`;`GET /sessions/{id}/messages`
- 回合流:`POST /sessions/{id}/turn/stream`(SSE)
- 模型:`GET /models`
- 自动更新:`GET /app/version`(无需登录)+ APK 静态文件(nginx 托管)
- baseURL:上架 `https://app.sophclaw.icu:18080/api`;开发期可指本地/st-e

## App 自动更新(OTA,Android 自建)

不依赖应用商店(国内 Google Play 不可用),App 自查新版、下载、安装。

### 后端(给 agent-cloud 新增)
- `GET /app/version` → `{version, build, apk_url, notes, force}`:当前最新版本信息(此接口**无需登录**,登录前也要能查/强更)。
- APK 托管:st-e nginx 服务静态 APK 文件(走现成 HTTPS),`apk_url` 指向它。
- 版本元数据来源:一份 `version.json`(发版时更新),nginx 直接读;或后端读配置返回。

### App(`core/update` 模块)
1. 启动时(+ 设置页"检查更新"按钮)调 `GET /app/version`。
2. 用 package_info_plus 取当前版本,与接口 `version` 比对。
3. 有新版 → 弹更新框(显示 `notes`):
   - `force=true`:**强制**,更新框无"稍后"、挡住后续操作,不更新不让用;
   - `force=false`:提示,可"稍后"跳过、继续用。
4. 用户确认 → 下载 APK(进度条)→ 调起系统安装(AndroidManifest 声明 `REQUEST_INSTALL_PACKAGES`)。

### 发布流程
`flutter build apk --release` → APK 传 st-e 托管目录 → 更新 `version.json`(版本号/url/notes/force)。做个一键发版脚本 `apps/mobile/scripts/release-apk.sh`。

### 注意
- Android 8+ 装未知来源 APK 需用户授权"允许此来源",首次引导用户开。
- 强更判断在**客户端比对**(后端给 version + force,App 决定挡不挡);后端不掌握每个用户的版本。
- `force` 用于后端出了**不兼容变更**时:把那一版标 force,逼旧客户端升级,避免旧 App 打不兼容接口报错。

## 测试

- **单元**:blocks 逻辑(`applyEvent`/`messagesToTurns`,移植 web 测试用例对齐)、SSE 解析、token 刷新拦截器(401→refresh→重试)。
- **Widget**:登录流、会话列表、聊天渲染(文本/工具/subagent 折叠卡)、发图。

## 实现顺序

1. **脚手架**:`flutter create apps/mobile` + pubspec 依赖 + 主题(teal)+ go_router 骨架。
2. **认证**:secure_storage + dio 拦截器(Bearer + 401 refresh)+ 登录/注册页。
3. **会话列表**:agent + sessions 拉取 + 列表 UI + 新建/切换/删除。
4. **聊天 + 回合流(核心)**:models + blocks 逻辑(移植 + 单测)+ SSE 解析 + 聊天页(历史重建 + live 渲染 + Composer)。
5. **多模态发图**:image_picker + turn/stream images。
6. **设置**:模型选择 + 登出。
7. **自动更新(OTA)**:后端 `GET /app/version` + nginx 托管 APK;App `core/update`(查版本 → 强更/提示 → 下载 → 安装)+ 发版脚本。

## 取舍 / 注意

- **SSE-over-POST 不是标准 EventSource**:必须用 streamed response 自解析(`http.Client().send(Request)` 或 dio `ResponseType.stream`),不能用 Dart 的 EventSource 类库。
- **开发期 Android 连明文 HTTP**(本地/st-e:18080)需 `network_security_config` 放开 cleartext(仅 debug);上架走 `https://app.sophclaw.icu:18080`。
- **refresh 一次性轮换 + 重用检测**:App 必须"刷新成功后立刻覆盖存储里的 token",否则并发刷新会触发后端的重用吊销(强制重登)。并发请求同时 401 时,刷新逻辑要串行化(单飞/锁),避免多个请求各自拿同一 refresh 去刷。
