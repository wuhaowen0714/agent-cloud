# 交互式终端设计

**日期:** 2026-06-11
**状态:** 设计已批准(对话中逐点敲定)

## 目标

工作区里一个 **Ghostty 风悬浮终端窗口**,经三跳双向流直连用户沙箱里的交互式 `bash`:
能跑 `vim`/`top`/`Ctrl-C`/ANSI 颜色,与 agent 共享同一个 per-user 沙箱(agent 刚写的文件、刚装的包,终端里立刻可见,反之亦然)。

## 已定决策

- **方案**:完整交互式(xterm.js + WebSocket + PTY),非简化命令框。
- **形态**:Ghostty quick-terminal 风**顶部下拉面板**——全视口宽,从屏幕顶部滑下(translateY 动画),深色、底部圆角+阴影,盖在侧栏与内容之上;底边可拖拽调高度(存 localStorage)。TopBar「终端」chip(Terminal 图标,与文件平行)开关,Esc / 收起按钮向上滑走。
  - **收起 ≠ 断开**:面板由 App 在首次打开后**常驻挂载**,chip/Esc 只驱动滑入/滑出动画;收起时 WS/PTY/xterm 缓冲全保留,再展开时跑着的进程与屏幕内容原样还在(刷新页面仍是新 shell:临时 PTY,历史/cwd 经软状态恢复)。
- **PTY 持久性**:临时——WS 断开/刷新即销毁 PTY 进程,重连是全新 shell。
- **状态保留**:工作区文件 + `pip --user`/`npm -g` 装的环境(本就在持久卷);**shell 历史**(HISTFILE 指向 `/workspace/.home/.bash_history`)+ **上次 cwd**(退出写 `.last_pwd`,启动 `cd` 回去)。不恢复正在跑的前台进程。
- **保活(第二档)**:WS 收到**用户输入(input 帧)**时节流续租沙箱 `last_used_at`;30 分钟无输入 → reaper 照常回收沙箱(纯看 `top` 不敲键盘超时会被回收,已接受,重连即恢复)。
- **并发**:v1 单终端。再开聚焦同一窗口,连同一个 per-user 沙箱。

## 架构 / 数据流(三跳双向流)

```
xterm.js ⟷WebSocket⟷ backend ⟷gRPC 双向流⟷ worker ⟷gRPC 双向流⟷ sandbox(PTY)
```

拓扑与现有 RunTurn 一致:**backend 不直连沙箱**(prod `network` 模式下沙箱在专属 docker 网,backend 够不到)。backend 从 `SandboxManager.get_endpoint_for_user` 拿 `SandboxConn{endpoint, token}`,经 gRPC **metadata** 传给 worker(`x-sandbox-endpoint` / `x-sandbox-token`),worker 用它连沙箱、做**纯透传桥**。

## proto

**sandbox.proto** 新增:
```proto
service Sandbox {
  rpc ExecTool(...) returns (...);          // 既有
  rpc Terminal(stream TerminalClientMsg) returns (stream TerminalServerMsg);
}
message TerminalClientMsg {
  oneof msg {
    TerminalStart start = 1;   // 首帧:开 PTY
    bytes input = 2;           // 键盘字节(含 Ctrl-C 等控制序列)
    TerminalResize resize = 3; // 窗口尺寸变化
  }
}
message TerminalStart { string work_subdir = 1; uint32 rows = 2; uint32 cols = 3; }
message TerminalResize { uint32 rows = 1; uint32 cols = 2; }
message TerminalServerMsg {
  oneof msg {
    bytes output = 1;       // PTY 输出(原始字节,含 ANSI)
    int32 exit_code = 2;    // shell 退出 → 收尾帧
  }
}
```

**worker.proto** 新增同形 `Terminal` RPC(各 package 内重声明同名消息)。backend↔worker 不用 start 帧携带 sandbox 连接信息,而是用 gRPC **metadata** 传 `x-sandbox-endpoint` / `x-sandbox-token`(与 sandbox 鉴权 token 既有用法对齐,不污染消息体)。

## 各层组件

### sandbox(`agent_cloud_sandbox`)

- **`pty_session.py`(新)**:`PtySession` 封装一个 PTY + 子进程 bash。
  - 起:`pty.openpty()` → `subprocess.Popen("bash --rcfile <注入rc>", preexec_fn=os.setsid, stdin/out/err=slave, cwd=workdir, env=...)`。
  - 注入 rc:`HISTFILE=/workspace/.home/.bash_history`、`PROMPT_COMMAND='history -a; pwd > /workspace/.home/.last_pwd'`、启动 `cd "$(cat /workspace/.home/.last_pwd 2>/dev/null)" 2>/dev/null || true`;`.home` 不存在先建。
  - async `read()`(`loop.add_reader(master_fd)`)、`write(bytes)`、`resize(rows, cols)`(`fcntl.ioctl(master, TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))`)、`close()`(`os.killpg(pgid, SIGKILL)` + `waitpid`,幂等)。
- **`server.py` `Terminal` handler**:**先复用 ExecTool 的 `x-sandbox-token` metadata 校验**;读首帧 `start` → `work_subdir` 经 `tools._resolve_within` 围栏校验 → 起 `PtySession`;两协程并发——client 流 `input`→`pty.write` / `resize`→`pty.resize`,`pty.read`→`yield output`;shell 退出 `yield exit_code`;`finally` 关 PTY。

### worker(`server.py` `Terminal` handler)

纯透传桥:从 metadata 取 `x-sandbox-endpoint` / `x-sandbox-token` → 开到 sandbox 的 `Terminal` 流(带 token metadata)→ `asyncio.gather` 双向泵(client→sandbox、sandbox→client)→ 任一端断开关另一端。

### backend(`api/terminal.py` 新)

- **WebSocket 端点 `/terminal`**(挂在 `/api` 下,与 SSE 同源):
  - **鉴权**:`<a> token` 走 WebSocket subprotocol(`sec-websocket-protocol: bearer, <access_token>`,因为浏览器 WS 不能带 Authorization header)。accept 前 `decode_access_token` + `UserRepository.get` 校验;失败 `close(1008)`。
  - **桥接**:`SandboxManager.get_endpoint_for_user(user_id)` → 开 worker `Terminal` gRPC 流(metadata 注入 endpoint+token)→ 两协程:`ws.receive`→worker、worker→`ws.send_bytes`。客户端 input 用二进制帧;resize 用文本帧(JSON `{rows,cols}`)区分。
  - **保活**:收到 input/resize 帧时节流(≥10s 一次)`SandboxRegistryRepository.touch`。
  - **清理**:WS 断 / worker 流断 → 关另一端(级联 kill PTY)。
- `main.py` 注册 router。

### frontend

- **依赖**:`@xterm/xterm` + `@xterm/addon-fit`。
- **`components/terminal/useTerminalSocket.ts`(新)**:`new WebSocket(wsURL, ["bearer", accessToken])`;`onmessage`(binary)→`term.write`;`term.onData`→`ws.send`(binary);FitAddon resize→`ws.send(JSON)` 节流;断开/退出回调暴露给面板做 UX。
- **`components/terminal/TerminalWindow.tsx`(新)**:Ghostty 风悬浮窗——`position:fixed`、深色背景、圆角+阴影、可拖标题栏移位、右下角 resize 手柄;xterm 容器随窗口尺寸 fit;位置/尺寸存 localStorage;关闭按钮 + Esc。`createPortal` 到 body(避开祖先 backdrop-filter / overflow 裁剪,与 RowMenu 同款教训)。
- **TopBar**:加「终端」chip(Terminal 图标),`onClick` toggle store `terminalOpen`(再开聚焦同一窗口)。
- **store**:`terminalOpen` + `toggleTerminal`。

## 生命周期 / 错误处理

| 事件 | 行为 |
|---|---|
| 点 chip 开 | WS 连;没沙箱则懒建(复用 per-user) |
| 30min 无输入 | reaper 回收沙箱 → 流断 → 前端「已因空闲回收,点击重连」 |
| 关页面/断网 | WS 断 → 级联 kill PTY |
| shell 退出(`exit`/进程死) | `exit_code` 帧 → 前端「会话已结束,点击重开」 |
| 沙箱/worker 不可达 | backend 关 WS 带原因 → 前端可重连(重连走 `get_endpoint_for_user` 重建,文件/历史/cwd 都在) |
| 再开终端 | 聚焦同一窗口,同一沙箱 |

## 安全

- **WS 鉴权**复刻 SSE 的 JWT + 多租户:subprotocol 取 token → 解析 user → 只连**自己**的沙箱(`get_endpoint_for_user` 按 user_id 路由)。鉴权写错 = 直接越权,是本功能最高风险面,需专门测跨租户拒绝。
- sandbox `x-sandbox-token` 校验复用既有;endpoint+token 经 gRPC metadata(不进消息体、不回前端)。
- 终端 = 完整 shell,能力等同 agent 的 bash;进程/FS 隔离靠沙箱现有(`cap_drop=ALL`、`no-new-privileges`、mem/CPU/PID 限额、per-user 卷);出网保持现状(`ALLOW_NET=true`)。
- PTY 输出是**原始字节**(含 ANSI):前端 xterm.js 渲染,后端/worker **不做行过滤**(现有 bash 工具过滤 gRPC fork stderr 噪声那套不适用于 PTY)。

## 测试

- **sandbox**:`PtySession` 起 bash、`echo hi` 读到 `hi`、`exit` 得 exit_code、`resize` 不抛(真 PTY);`Terminal` handler token 拒绝、work_subdir 围栏。
- **worker**:`Terminal` 透传 + metadata 解析 + 断流级联清理(fake sandbox 回显流)。
- **backend**:WS 鉴权(有效连上 / 无 token 拒 / **跨租户拒**)、桥接回显、input 触发节流续租、断连清理(fake worker)。
- **frontend**:`useTerminalSocket`(连接/重连/resize 节流,WS mock)、`TerminalWindow`(拖拽移位、resize、localStorage、Esc 关闭;xterm mock)、TopBar chip;vitest。
- **真机**(dev 栈 docker publish):开终端 → `ls`/`pwd`/`vim` 进退 / `top` / `Ctrl-C` / 拖拽 resize 不错位 / 关开重连保留历史&cwd / 空闲回收后重连;console 干净。

## 非目标(YAGNI)

多标签/分屏、tmux 式进程持久(关页面恢复跑着的进程)、终端内文件上传、命令历史搜索 UI、会话录制回放、多终端并发。
