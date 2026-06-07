# 文件管理(File Management)— 设计文档

> 日期:2026-06-07 · 关联:[[stateless-agent-cloud-design]] §2(文件模型)、[docker-sandbox-provisioner-design](2026-06-07-docker-sandbox-provisioner-design.md)

## 1. 背景与目标

用户的工作区(`/workspace`)是**用户级、跨所有会话/agent 共享**的持久目录(见 user-level workspace 决策)。目前用户**没有任何方式查看或管理**这些文件——只能让 agent 在对话里 `ls`。

**目标**:给工作区一个完整的文件管理器:浏览、在线预览、上传、下载、删除、重命名、新建文件夹。前端用右侧滑出抽屉;后端经 `FileStore` 抽象**直接操作宿主上的工作区目录**。

**核心约束**:工作区目录就是绑定挂进沙箱 `/workspace` 的那个宿主目录,所以:
- 上传/修改对**正在运行的沙箱即时可见**(同一挂载);
- 浏览/管理**不依赖沙箱在跑**(沙箱空闲被回收也能用)——直接读宿主目录。

## 2. 范围

**v1 做**:浏览目录树、文本/代码/图片在线预览、上传(多文件 + 拖拽)、下载(文件;目录打 zip)、删除(文件/目录递归)、重命名/移动、新建文件夹。

**v1 不做**:对象存储备份/快照(留作未来 `FileStore` 实现)、浏览器内**编辑**(预览只读,改靠重传)、版本历史、搜索、分享、鉴权(沿用当前"前端传 user_id、暂无 auth"模型)。

## 3. 架构总览

```
前端 FileDrawer ──REST(multipart/JSON/stream)──▶ 后端 api/files.py
                                                      │
                                                      ▼
                                              FileStore(接口)
                                                      │ v1
                                              LocalFileStore
                                                      │ 直接读写
                                    <host_root>/<user_id>/workspace/…(宿主目录)
                                                      ▲ 同一目录绑定挂载
                                                      │
                                                  沙箱容器 /workspace
```

- 后端本就负责构造该卷(`DockerProvisioner` 把 `<host_root>/<uid>/workspace` 挂到容器 `/workspace`),因此**后端进程能直接读写这个宿主目录**。
- `FileStore` 把"对某用户工作区的文件操作"抽象出来;v1 用 `LocalFileStore`(本地文件系统),将来 k8s / 对象存储是**同一接口的另一实现**,API 与前端不变。
- 宿主根路径取 `Settings.effective_sandbox_host_root`(= `sandbox_host_root or sandbox_base_root`),与 provisioner 用的同一个值,保证 inprocess 与 docker 两种 provisioner 下路径一致。

### 3.1 文件属主说明(A 方案已知点)

沙箱容器以 root 跑,Linux 宿主上其产物属 root,后端(非 root)删/改可能受限。**macOS Docker Desktop 的挂载做了 uid 虚拟化,开发机不受影响**;Linux 生产靠延后项"沙箱非 root + 对齐 uid"解决(见 [[project_sandbox]])。本 spec 不解决属主对齐,仅在测试/文档里标注该前提。

## 4. FileStore 接口与实现

`services/backend/src/agent_cloud_backend/files/store.py`:

```python
from dataclasses import dataclass
from typing import BinaryIO, Iterator, Protocol

@dataclass
class FileEntry:
    name: str        # 基名,如 "app.py"
    path: str        # 相对工作区根的 posix 路径,无前导 "/",根目录为 ""
    is_dir: bool
    size: int        # 字节;目录为 0
    mtime: float     # epoch 秒

class FileStore(Protocol):
    def list_dir(self, user_id: str, rel_path: str) -> list[FileEntry]: ...
    def stat(self, user_id: str, rel_path: str) -> FileEntry: ...
    def open_read(self, user_id: str, rel_path: str) -> BinaryIO: ...      # 下载/预览
    def write(self, user_id: str, rel_path: str, data: BinaryIO, max_bytes: int) -> FileEntry: ...  # 上传
    def mkdir(self, user_id: str, rel_path: str) -> FileEntry: ...
    def move(self, user_id: str, src: str, dst: str) -> FileEntry: ...
    def delete(self, user_id: str, rel_path: str) -> None: ...             # 文件或目录(递归)
    def zip_dir(self, user_id: str, rel_path: str) -> Iterator[bytes]: ...  # 目录打 zip 流式
```

`LocalFileStore(host_root: str)`:
- `_user_root(user_id) -> Path` = `Path(host_root)/user_id/"workspace"`;**懒创建**(`mkdir(parents=True, exist_ok=True)`),新用户没跑过沙箱时浏览得到空目录、可直接上传。
- 所有方法先经 `_resolve(user_id, rel_path)` 拿到围栏内的绝对 `Path`(见 §5),再用 `pathlib`/`shutil` 实现。
- `write`:边写边累计字节,超 `max_bytes` 立刻中止并删除半截文件,抛 `FileTooLarge`。
- `delete`:文件 `unlink`;目录 `shutil.rmtree`(仅围栏内)。
- `zip_dir`:用 `zipfile` 写进一个生成器/临时缓冲,流式产出。
- `list_dir` 返回按 **(目录优先,名称升序)** 排序,保证确定性(便于前端展示与测试断言)。

### 4.1 错误类型(`files/errors.py`)

| 异常 | 含义 | API 映射 |
|---|---|---|
| `PathEscape` | 路径越出工作区围栏 | 400 |
| `FileNotFound` | 目标不存在 | 404 |
| `FileTooLarge` | 上传超限 | 413 |
| `FileConflict` | mkdir/move 目标已存在 | 409 |
| `NotADirectory` / `IsADirectory` | 操作与类型不符(如对文件 list_dir) | 400 |

## 5. 路径围栏(安全核心,test-first)

`LocalFileStore._resolve(user_id, rel_path) -> Path`:
1. 先**防御式拒绝**:`rel_path` 含 `\0`、为绝对路径(`startswith("/")` 或盘符)、或拆分后任一段为 `..` → 抛 `PathEscape`。
2. `candidate = (_user_root(user_id) / rel_path).resolve()`(`resolve()` 跟随符号链接并规范化;Python 默认 `strict=False`,不存在的路径也能解析)。
3. `root = _user_root(user_id).resolve()`;断言 `candidate == root or root in candidate.parents`,否则抛 `PathEscape`。
   - 该断言同时挡住**符号链接越狱**:指向外部的 symlink `resolve()` 后落在 root 外 → 拒绝。

复用沙箱 `tools.py` 里 `_resolve_within` 的同一思路(沙箱已用它把 `read_file`/`write_file` 限制在 work_subdir)。围栏是文件功能的**安全边界**,必须 test-first 覆盖:`..`、绝对路径、`\0`、symlink 越狱全部拒绝。

## 6. 后端 API(`api/files.py`)

REST,挂在 `/files` 前缀;GET 用查询参数,写操作用 JSON/multipart。`user_id` 由前端传入(沿用现有模型,暂无 auth)。`path` 相对工作区根,默认 `""`(根)。

| 方法 & 路径 | 入参 | 返回 | 说明 |
|---|---|---|---|
| `GET /files` | `user_id`, `path=""` | `list[FileEntryRead]` | 列目录;`path` 指向文件 → 400(预览用 raw) |
| `GET /files/raw` | `user_id`, `path`, `attachment=false` | 字节流 | 文件:按 content-type(`mimetypes.guess_type` 按扩展名,未知用 `application/octet-stream`)流式返回;`attachment=true` 走下载(`Content-Disposition: attachment`),否则 inline(供预览/`<img>`)。目录:强制打 zip 下载,文件名 `<dir>.zip` |
| `POST /files/upload` | `user_id`, `path`(目标目录);multipart 字段 `files`(可多个) | `list[FileEntryRead]` | 每文件超 `file_upload_max_bytes` → 413;文件名取 basename 消毒 |
| `POST /files/mkdir` | JSON `{user_id, path}` | `FileEntryRead` | 已存在 → 409 |
| `POST /files/move` | JSON `{user_id, src, dst}` | `FileEntryRead` | 重命名/移动;`dst` 已存在 → 409 |
| `DELETE /files` | `user_id`, `path` | 204 | 文件或目录(递归) |

- Pydantic schema `FileEntryRead`(`schemas/file.py`):字段同 `FileEntry`。
- 依赖 `get_file_store`(`api/deps.py`):构造 `LocalFileStore(settings.effective_sandbox_host_root)`。
- 路由在 `main.py` 注册。
- 预览大小不在后端设限(raw 要能下载完整文件);**预览的大小/类型门槛在前端**(列表已带 `size`,前端只对小于上限的文本/图片才发 raw 预览请求)。

### 6.1 配置(`config.py`)

- `file_upload_max_bytes: int = 100 * 1024 * 1024`(100 MB,单文件上限)。

## 7. 前端(右侧抽屉)

入口:顶部(`UserBar` 旁)一个"文件"按钮 → 切换右侧滑出抽屉。工作区是用户级,故抽屉**独立于当前会话**,任何时候可开。

**状态**:`store.ts` 加 `fileDrawerOpen: boolean` + `toggleFileDrawer()`;当前路径用抽屉内部 state。列表用 TanStack Query key `["files", userId, path]`;增删改 mutation 成功后失效该 key 重拉。

**组件**(`components/files/`):
- `FileButton` — 顶部按钮,切 `fileDrawerOpen`。
- `FileDrawer` — 固定右侧滑出层(`translate-x` 过渡 + 半透明遮罩);容纳下列:
  - `FileBreadcrumb` — 路径分段,点击跳转;根为"工作区"。
  - `FileToolbar` — 上传(文件选择器 + 拖拽放置到当前目录)、新建文件夹、刷新。
  - `FileList` — 行:类型图标、名称(目录→进入,文件→预览)、大小、修改时间;行内操作:下载、重命名、删除(目录删除二次确认)。
  - `FilePreview` — 内联/模态:文本/代码用现有代码样式渲染(`.md` 走 Markdown)、图片用 `<img src={rawUrl}>`、其余(二进制/超上限)给"下载"入口。
- 拖拽:文件拖到抽屉 → 上传到当前目录。

**API client(`api/client.ts`)新增**:`listFiles(userId, path)`、`fileRawUrl(userId, path, {attachment})`(返回 URL,供 `<img>`/下载链接)、`uploadFiles(userId, path, files)`、`mkdir(userId, path)`、`moveFile(userId, src, dst)`、`deleteFile(userId, path)`。`types.ts` 加 `FileEntry`。

**纯逻辑**(单测):面包屑拆分、人类可读大小格式化、预览类型判定(按扩展名/大小决定 文本/图片/仅下载)。

## 8. 数据流

1. 点"文件" → 抽屉开 → `GET /files?user_id&path=""` → 列根目录。
2. 点目录 → 改当前路径 → 重新查询;点文件 → 按类型/大小决定预览方式(文本/图片发 `GET /files/raw?attachment=false`,大文件/二进制只给下载)。
3. 上传(拖拽或选择)→ `POST /files/upload` → 失效列表重拉(对运行中沙箱即时可见)。
4. 新建夹/重命名/删除 → 对应写操作 → 失效列表重拉。
5. 下载 → 浏览器打开 `GET /files/raw?attachment=true`(目录则得到 zip)。

## 9. 默认值与限制

| 项 | 默认 |
|---|---|
| 单文件上传上限 | 100 MB(`file_upload_max_bytes`)→ 超 413 |
| 文本预览上限 | 1 MB(前端常量)→ 超只给下载 |
| 图片内联预览 | png/jpg/jpeg/gif/svg/webp(按扩展名) |
| 文件夹下载 | 打成 `.zip` |
| 删除目录 | 递归;前端二次确认 |
| 上传 | 多文件 + 拖拽 |

## 10. 安全

- **路径围栏**(§5):所有路径经 `_resolve` 限制在该用户工作区内;test-first 覆盖 `..`/绝对/`\0`/symlink 越狱。
- **上传大小限制**:边写边计,超限中止 + 删半截 + 413。
- **文件名消毒**:上传文件名只取 basename(剥离任何路径分隔符),拼到目标目录下。
- **删除/移动**仅在围栏内;不跟随越狱 symlink。
- `user_id` 由前端传入,沿用当前无 auth 模型(与 sessions/agents 等一致);**鉴权是独立的后续工作**,不在本 spec。

## 11. 测试策略

- **后端 `tests/test_filestore.py`**(test-first 安全围栏):
  - 围栏:`..`、绝对路径、`\0`、symlink 指向外部 → 全抛 `PathEscape`。
  - 功能:`list_dir`/`stat`/`open_read`/`write`/`mkdir`/`move`/`delete`/`zip_dir`;懒创建根;`write` 超 `max_bytes` 抛 `FileTooLarge` 且不留半截文件。
- **后端 `tests/test_files_api.py`**:各端点 happy-path + 错误码(围栏 400、404、超限 413、冲突 409);上传 multipart;目录下载得到 zip;`DELETE` 递归。
- **前端**:`FileDrawer`/`FileList` 组件测试(渲染条目、进入目录、预览分支按类型/大小、上传触发 mutation、删除二次确认);纯逻辑(面包屑、大小格式化、预览类型判定)单测。
- 用临时目录作 `host_root`;不依赖真实沙箱/Docker。

## 12. 后续演进

- 对象存储 `FileStore` 实现(备份/快照/跨节点);k8s 下后端与沙箱不共享盘时切换。
- 浏览器内编辑(文本编辑器 + 保存)。
- 大文件分块/断点上传;目录上传。
- 鉴权(整体 auth 落地后,文件 API 复用)。
- 沙箱非 root + uid 对齐,使 Linux 生产下后端对沙箱产物有完整读写权(见 [[project_sandbox]])。
