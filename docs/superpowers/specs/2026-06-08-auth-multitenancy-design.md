# 鉴权 / 多租户 / BYO-Key + 前端外壳重设计 — 设计文档

> 日期:2026-06-08 · 关联:[[2026-06-05-stateless-agent-cloud-design]](§2 认证/编排)、roadmap.html P1 · architecture.html §6(安全分层)

## 1. 目标与范围

把"单人强原型"变成可安全对外的**多租户**系统:用户有真实身份(注册/登录),只能访问**自己的**资源,并可**自带 LLM Key(BYO-Key)**。同时借此重做前端外壳(登录页 + 侧栏)。

**核心(做)**:邮箱+密码注册/登录/登出;JWT access(短期)+ 服务端 refresh token(可吊销、轮换);`get_current_user` 依赖;**所有资源按 owner 隔离**(后端从 token 取 user,删客户端传入 user_id,越权 404);BYO-Key(每用户加密存储 provider 凭证,回合按 agent 选用,回退全局);前端登录/注册/登出 + token 自动刷新 + **侧栏重设计** + 凭证管理 UI。

**不做(留后续)**:邮箱验证、找回密码、第三方 OAuth、限流/配额、组织/团队(租户 = 用户)、真 KMS(用 env 主密钥,接口 KMS-ready)。

**安全前提**:worker/sandbox 不改鉴权(内网可信);user_id 仍由后端下发给 worker;**Key 永不进 sandbox**。

## 2. 数据模型

- `users`:加 `password_hash: str`(argon2id)。现有无密码 dev 用户 → 清库重建。
- 新 `refresh_tokens`:`(id, user_id FK, token_hash, expires_at, revoked_at nullable, created_at)`。refresh 是随机不透明串,只存其哈希(sha256);使用时轮换(旧的置 revoked,发新的)。
- 新 `provider_credentials`:`(id, user_id FK, name, base_url, api_key_encrypted bytes, created_at)`。api_key 用后端主密钥 AES-GCM 加密落库;读取时解密。
- `agent_configs.key_ref`:复用为可空的 `provider_credentials.id`(字符串)。空 → 回合用全局 Key。

迁移:alembic 加上述列/表。

## 3. AuthN(认证)

端点(新 `api/auth.py`,prefix `/auth`):
- `POST /auth/register {email, password}` → 邮箱唯一性校验、argon2id 哈希、建 user → body 返回 `{access, user}`,并 **set refresh cookie**。
- `POST /auth/login {email, password}` → 验密码 → body 返回 `{access, user}` + set refresh cookie。
- `POST /auth/refresh`(无 body,读 refresh cookie)→ 查 token_hash:存在/未吊销/未过期 → 返回新 access + **轮换** refresh cookie(旧置 revoked)。**重用检测**:若 cookie 里是已 revoked 的 token(宽限外)→ 视为泄露,吊销该用户全部 refresh,返回 401(前端跳登录)。
- `POST /auth/logout` → 读 refresh cookie 吊销之 + 清 cookie(access 失效也能登出)。
- `GET /auth/me`(需登录)→ 返回当前 user。

令牌与传输:
- **access**:JWT,HS256,后端 secret(env `AGENT_CLOUD_AUTH_SECRET`),claims `{sub: user_id, exp}`,TTL ~15min。**前端放内存**,以 `Authorization: Bearer` 发送(含 fetch 流式 SSE)。
- **refresh**:`secrets.token_urlsafe(32)`,TTL ~30d,**只存哈希**;以 **httpOnly + Secure + SameSite=Lax cookie**(path `/auth`)下发,前端 JS 读不到(防 XSS 窃取)、CSRF 由 SameSite 兜住、且只随 `/auth/*` 请求发送(不污染 SSE/turn)。
- 密码:argon2id(`argon2-cffi`)。

## 4. AuthZ(租户隔离 —— 关键一半)

- `get_current_user`(`api/deps.py`):取 `Authorization: Bearer <access>` → 验 JWT(签名+exp)→ 载入 user;缺失/无效/过期 → 401。
- **所有端点改造**:把客户端传入的 `user_id` 全部换成 `current_user.id`。受影响:`sessions`、`agent_configs`、`context_documents`、`memory_entries`、`messages`、`files`、`skills`、`turn`(及 schema:去掉 body/query 里的 user_id/owner_id)。
- **归属校验**:按 id 访问资源时校验 `resource.user_id == current_user.id`(message/turn/files 经 session→user);不符 → **404**(不泄漏存在性)。仓库层加 `get_owned(id, user_id)` 之类约束,避免漏判。
- 删 `POST /users`(由 `/auth/register` 取代)、用户列举/切换相关端点。

## 5. BYO-Key

- 新 `api/credentials.py`(prefix `/credentials`,均需登录、限本人):
  - `POST` `{name, base_url, api_key}` → 加密存储 → 返回(api_key 掩码,如 `sk-…1234`,绝不回明文)。
  - `GET` → 列出本人凭证(掩码)。`DELETE /{id}`。
- 加密:`crypto.py` 用 env `AGENT_CLOUD_CREDENTIAL_KEY`(32B base64)做 AES-GCM;`encrypt(plain)->bytes` / `decrypt(bytes)->plain`;接口可后续换 KMS。
- 回合流程(`turn/assemble.py` + `worker_client`):后端按 `agent.key_ref` 取本人 credential → 解密 → 把 `api_key`+`base_url` 放进 RunTurn 的 `Agent`;无 key_ref/credential → 留空,worker 回退全局。
- proto:`Agent` 加 `string api_key = 6; string base_url = 7;`(后端填、worker 用)。**仅 BE→Worker;不进 sandbox**(sandbox 只收工具调用)。
- worker `factory`:若 `api_key` 非空 → 用请求里的 key/base_url 造 client;否则用 `settings` 全局。worker 仍无状态。
- 安全:明文 key 不落日志、不回前端;UI 掩码;传输走内网(prod 加 mTLS)。

## 6. 前端 UI/UX 设计(重点:登录页 + 侧栏重做)

设计语言沿用:浅色 + teal 强调、圆角(rounded-lg)、克制留白、统一 8px 间距节奏。

### 6.1 登录 / 注册页(新)
- 未登录 → 渲染居中卡片(非侧栏布局):顶部 logo mark + "Agent Cloud" 字标;邮箱 + 密码输入(统一描边/聚焦 teal ring);主按钮(teal,全宽);底部"没有账号?注册 / 已有账号?登录"切换;行内错误提示(邮箱占用/密码错);提交 loading 态。
- 登录成功 → access 存内存(zustand),refresh 由后端写入 httpOnly cookie → 进主界面。

### 6.2 侧栏重做(修掉当前丑点)
当前问题(实测截图):① 用户行直接显示原始 UUID + 细小"切换";② agent 用原生 `<select>` + 挤压的描边图标;③ "工作区/文件"单开一节孤立;④ "＋新会话"淡灰禁用像坏的;⑤ 大写灰标签噪音;⑥ 品牌纯文字。

新结构(自上而下):
1. **品牌头**:teal 圆角 logo mark(单字形/简标)+ "Agent Cloud" 字标;低调一行。
2. **主操作 `＋ 新对话`**:醒目全宽 teal 按钮(主按钮样式,非淡灰链接)。无 agent 时:点击引导先选/建 agent(或禁用并 tooltip,但用清晰的禁用主按钮样式)。
3. **Agent 切换器**:**弃用原生 select**,改自定义控件——一个圆角按钮显示当前 agent(`名称 · 模型`,模型小字次要色),点开 popover 菜单:列出 agents(选中打勾)+ 分隔线 + "⚙ agent 设置" + "＋ 新建 agent"。与 teal/圆角一致,图标不再挤压。
4. **对话列表**:轻量分节标题"对话"(弱化,不全大写堆叠);行:圆角、hover bg、选中 = teal 浅底 + 左侧 teal 竖条 + 中等字重;空态 = 居中淡色图标 + "还没有对话,点上面新建";占据剩余高度、可滚动。
5. **底部账户区**(替换顶部 UUID 行):贴底——头像(邮箱首字母 teal 圆)+ 邮箱(截断)+ `⋯`/chevron 打开菜单:`工作区文件` / `Provider Keys` / `账户设置` / `登出`。"工作区文件"从独立一节移到这里(或作为列表上方一个清爽的图标行),不再孤立。
- 整体:减少大写标签、统一间距、teal 仅用于强调(主操作/选中/头像)。

### 6.3 凭证(BYO-Key)UI
- 设置抽屉(复用现有 SettingsDrawer)新增 "Provider Keys" 区:列出凭证(名称、base_url、`sk-…1234` 掩码、删除);新增表单(name / base_url / api_key,密码型输入)。
- agent 设置里加"使用凭证"下拉(key_ref):默认"全局共享 Key",可选本人某凭证。
- 账户区菜单可直达该设置。

### 6.4 token / 请求接线
- access 在内存(zustand);`api/client` 统一附 `Authorization: Bearer <access>`(含 fetch 流式 `streamTurn`/`resumeTurn`)。
- **应用加载时**:access 不持久化,故先静默调 `POST /auth/refresh`(带 cookie)拿一枚新 access;成功→进主界面,失败→登录页。
- **401 拦截**:任意请求 401 → 调 `/auth/refresh` 换新 access 重试一次;再失败 → 清内存 access、跳登录页。
- 登出 → `POST /auth/logout`(清 cookie)+ 清内存 access + 回登录页。
- 删除 localStorage 假用户(`ac.userId`)+ UserBar 切换逻辑;`ac.sessionId` 仍可留(当前会话持久)。

## 7. 迁移 / 破坏性变更

- DB:`users.password_hash` + `refresh_tokens` + `provider_credentials` 迁移。
- API:所有曾收 `user_id` 的端点改为从 token 取;`POST /users` 移除。前端/任何客户端必须带 token。
- dev 数据:旧用户无密码 → 清 dev 库(`dev_up.sh` 重建)或种一个已知账号(plan 里给步骤)。
- 配置:新增 `AGENT_CLOUD_AUTH_SECRET`、`AGENT_CLOUD_CREDENTIAL_KEY`(写进 `.env.example`)。

## 8. worker / sandbox 影响

- worker:`factory` 支持按请求 key/base_url(小改);proto 加 2 字段;无状态不变。
- sandbox:**完全不变**,永不见 Key。

## 9. 测试

- AuthN:注册(邮箱唯一)、登录(对/错密码)、refresh 轮换、重用检测吊销全部、登出吊销、access 过期、argon2 往返。
- AuthZ:无/坏 token→401;跨用户访问每类资源→404;同用户正常。
- BYO-Key:凭证 CRUD + 掩码;加解密往返;回合用上本人 key(假 worker 捕获 api_key/base_url)+ 无 key_ref 回退全局;凭证属他人→404。
- 前端:登录/注册/登出;token 挂载;401 自动刷新重试;侧栏(agent 菜单、新对话、账户菜单)渲染与交互;凭证 UI。
- 全栈回归 + ruff/tsc 绿;关键页面 live 截图验收(登录页 + 新侧栏)。

## 10. 我替你定的默认值

1. BYO-Key 回退:没配 → 用全局 Key(BYO 可选覆盖)。
2. 加密:env 主密钥 AES-GCM,KMS-ready 接口。
3. refresh 轮换 + 重用检测;access ~15min、refresh ~30d。
4. 越权 → 404。
5. `key_ref` 复用为 credential id。
6. 密码 argon2id。

## 11. 实现切分(预计)

- **Plan A(auth 核心 + 隔离)**:数据模型/迁移、`auth.py`(register/login/refresh/logout/me)、`get_current_user`、全端点改 owner 化、移除 user_id 入参 + 后端测试。
- **Plan B(前端外壳)**:登录/注册页、token 接线 + 401 刷新、侧栏重做、账户区/菜单、删假用户 + 前端测试 + live 截图。
- **Plan C(BYO-Key)**:`provider_credentials` + crypto、`credentials.py`、proto 2 字段 + worker factory、assemble 解析 key、凭证 UI + agent 选凭证 + 测试。

(三者有依赖:B 依赖 A;C 依赖 A、UI 部分依赖 B。)
