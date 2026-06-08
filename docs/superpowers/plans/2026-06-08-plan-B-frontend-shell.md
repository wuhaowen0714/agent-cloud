# Plan B:前端外壳(登录/注册 + token 接线 + 侧栏重做)实现计划

> REQUIRED SUB-SKILL: subagent-driven-development / executing-plans。Plan A 已落地(后端鉴权+隔离),前端当前与新后端不兼容,本 plan 修复并重做外壳。Spec:[2026-06-08-auth-multitenancy-design.md](../specs/2026-06-08-auth-multitenancy-design.md) §6。

**Goal:** 登录/注册页;access 内存 + Bearer 附带 + 加载静默刷新 + 401 自动刷新重试;所有 api 去掉 user_id;侧栏重做(账户区 / agent 切换器 / +新对话 等);登出。完成后 app 重新可用。

测试:`cd frontend && npx vitest run …`;类型:`npm run lint`(tsc)。

## 文件结构
- 新:`api/auth.ts`(token holder + refresh 单飞 + register/login/logout)、`components/AuthGate.tsx`(登录/注册页)、`components/Sidebar/*` 重做(或就地重写 Sidebar.tsx + 新 `AccountMenu.tsx`、`AgentSwitcher.tsx`)。
- 改:`api/client.ts`(http 加 header+401刷新;去 user_id)、`api/stream.ts`(加 header)、`store.ts`(user/userId 派生/setAuth/logout)、`App.tsx`(鉴权 gate + bootstrap)、`SessionList.tsx`/`AgentSelector.tsx`/`FileDrawer.tsx`/`FileToolbar.tsx`/`FilePreview.tsx`/`settings/*`(去 user_id 入参)、删 `UserBar.tsx`。

---

## Task 1:auth 模块 + http 接线 + store

- [ ] **api/auth.ts**:
```ts
let _access: string | null = null
let _onUnauth: () => void = () => {}
export const setAccess = (t: string | null) => { _access = t }
export const getAccess = () => _access
export const authHeader = (): Record<string, string> => (_access ? { Authorization: `Bearer ${_access}` } : {})
export const setOnUnauth = (fn: () => void) => { _onUnauth = fn }
export const onUnauth = () => _onUnauth()

let _refreshing: Promise<string | null> | null = null
export function refreshAccess(): Promise<string | null> {
  if (!_refreshing) {
    _refreshing = (async () => {
      const res = await fetch("/api/auth/refresh", { method: "POST" })
      if (!res.ok) { setAccess(null); return null }
      const { access_token } = await res.json()
      setAccess(access_token)
      return access_token as string
    })().finally(() => { _refreshing = null })
  }
  return _refreshing
}
```
- [ ] **api/client.ts http()**:附 `...authHeader()`;401 → `refreshAccess()`,成功重试一次,失败 `onUnauth()` 并抛。签名 `http<T>(path, init?, retry = true)`。
- [ ] **store.ts**:`LiveTurn` 不变;`AppState`:`user: User|null`、`userId: string|null`(派生)。去掉旧 `setUser`(localStorage 假用户),加 `setAuth(user: User|null)`(set user + userId=user?.id ?? null;切用户清 agentId/sessionId)、`logout()`(setAccess(null)+setAuth(null)+清 ac.sessionId)。`userId` 初值不再从 localStorage 读(改由 bootstrap 决定)。`setOnUnauth(() => useStore.getState().logout())` 在 store 末尾注册。

- [ ] 类型 `User` 已存在(types.ts)。运行 `npm run lint`(tsc)确保编译(组件可能临时红,先让本任务文件通过)。

---

## Task 2:api/client.ts 去 user_id + stream 加 header

- [ ] **api/client.ts**:删 `createUser`/`getUser`;加 `register(email,password)`/`login(email,password)`(返回 `{access_token, user}`,内部 `setAccess`)、`logout()`(POST /auth/logout)、`me()`。各业务方法去 user_id:
  - `listAgents()`、`createAgent({name,model,provider})`、`listSessions()`、`createSession({agent_config_id,title?})`、`listFiles(path)`、`fileRawUrl(path,attachment?)`(注意:`fileRawUrl` 给 `<img src>`/`<a href>` 直用,**带不了 Authorization header** → 见 Task 5 处理)、`uploadFiles(path,files)`、`mkdir(path)`、`moveFile(src,dst)`、`deleteFile(path)`、`listDocs(scope, agentId?)`(user scope 不传 agent_id;agent scope 传 `&agent_id=`)、`putDoc(scope,type,content,agentId?)`、`listSkills()`、`installSkill(name)`。
  - `uploadFiles`/`fileRawUrl` 用原始 fetch,需手动加 `authHeader()`(upload)。
- [ ] **api/stream.ts**:`streamTurn`/`resumeTurn` 的 fetch 加 `headers: { ...authHeader() }`;401 时 `await refreshAccess()` 后重试一次(失败 → 抛,ChatView 显示错误)。`cancelTurn` 同加 header。

---

## Task 3:App 鉴权 gate + bootstrap + Login/Register

- [ ] **App.tsx**:
```tsx
const [booting, setBooting] = useState(true)
const user = useStore(s => s.user)
const setAuth = useStore(s => s.setAuth)
useEffect(() => {
  (async () => {
    const tok = await refreshAccess()           // 用 cookie 静默换 access
    if (tok) { const u = await api.me().catch(() => null); useStore.getState().setAuth(u) }
    setBooting(false)
  })()
}, [])
if (booting) return <全屏 loading>
if (!user) return <AuthGate />
return <现有主布局(Sidebar + main + drawers)>
```
- [ ] **components/AuthGate.tsx**:居中卡片;logo mark + "Agent Cloud";登录/注册切换(`mode` state);email + password 输入(teal focus ring);主按钮(teal,全宽,loading 态);行内错误(邮箱占用 409 / 凭证错 401 / 密码<8);提交成功 → `api.login/register` 设 access + `setAuth(user)`。

---

## Task 4:侧栏重做(修丑点)

- [ ] **Sidebar.tsx** 重写,自上而下:
  1. **品牌头**:teal 圆角小 logo(单字 "A" 或简标)+ "Agent Cloud" 字标。
  2. **`＋ 新对话`** 全宽 teal 主按钮(无 agent 时禁用,tooltip "先选/建 agent")——取代淡灰禁用链接。
  3. **AgentSwitcher**(新组件,替换原生 select):按钮显示当前 agent(`名称 · 模型`),点开 popover:agents 列表(选中打勾)+ 分隔 + "⚙ agent 设置" + "＋ 新建 agent"。
  4. **对话列表**(SessionList,去掉自带的"＋新会话",标题弱化为"对话";空态居中淡色)。
  5. **底部账户区**(AccountMenu,新组件,贴底):首字母 teal 圆头像 + 邮箱(截断)+ chevron;点开菜单:`工作区文件`(开 FileDrawer)、`登出`(store.logout)。(Provider Keys 入口 Plan C 加。)
- [ ] **删 UserBar.tsx**;新建 `components/AgentSwitcher.tsx`、`components/AccountMenu.tsx`。
- [ ] 设计语言:浅色 + teal 强调、rounded-lg、统一间距;teal 仅用于主操作/选中/头像。

---

## Task 5:组件去 user_id

- [ ] `SessionList.tsx`:`api.listSessions()`、`api.createSession({agent_config_id: agentId!})`;query key 仍可用 `["sessions", userId]`(userId 来自 store 派生);`if (!userId) return null` 保留(未登录不渲染,但 App 已 gate)。去掉自带"＋新会话"(移到 Sidebar 主按钮)或保留——以 Sidebar 重做为准。
- [ ] `AgentSelector.tsx`:并入/被 AgentSwitcher 取代;`api.listAgents()`。
- [ ] `settings/AgentSettings.tsx`/`SkillsPanel.tsx`/`SettingsDrawer.tsx`:`api.listAgents()`/`createAgent({...draft})`/`listSkills()`/`installSkill(name)`/`listDocs("agent", agentId)`/`putDoc("agent","AGENTS",instructions, agentId?)`——注意 putDoc/listDocs 的 agent scope 传 agentId。
- [ ] `files/FileDrawer.tsx`/`FileToolbar.tsx`/`FilePreview.tsx`:`api.listFiles(path)`/`uploadFiles(path,files)`/`mkdir(path)`/`moveFile(src,dst)`/`deleteFile(path)`;**FilePreview/下载用 fileRawUrl**:由于 `<img>/<a>` 带不了 Bearer,改为 `api.fileRawUrl(path)` 现在不含 user_id,但需 cookie 鉴权——而我们用 Bearer 不用 cookie。**方案**:预览改用 fetch(带 header)→ blob URL;下载改用 fetch→blob→`<a download>`。(在 FilePreview/列表下载处实现一个 `fetchBlobUrl(path)`。)

---

## Task 6:测试 + 收尾

- [ ] `AuthGate.test.tsx`:渲染登录态、切换注册、提交调用 api.login/register(mock)。
- [ ] `Sidebar`/`AccountMenu` 基本渲染 + 登出调用。
- [ ] `npx vitest run` 全绿;`npm run lint`(tsc)无错。
- [ ] 提交。

---

## Task 7:live-verify
- [ ] 重启栈(新后端+新前端)。注册→登录→建 agent→新对话→发消息→看流式;截图新侧栏;登出回登录页;刷新后静默续登。

## Self-Review
- Spec §6 覆盖:登录/注册页 ✓;access 内存+Bearer+加载刷新+401重试 ✓;侧栏重做(账户区/AgentSwitcher/+新对话/去 UUID 行/去原生 select)✓;去 user_id ✓;登出 ✓。
- 文件下载/预览带不了 Bearer → 改 fetch+blob(Task 5 显式处理)。
- BYO-Key 凭证 UI 在 Plan C(账户菜单留入口)。
