# 图片理解(多模态)实现计划

> **执行方式**:本仓库作者(controller)inline 执行,熟悉现有代码与模式;故代码块聚焦**关键/非显然**处,常规改动按现有文件模式跟写。每个任务自带测试,**每步跑该层全套回归**(后端 `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker"`;前端 `npm run lint && npx vitest run`),全绿才 commit。设计见 [spec](../specs/2026-06-19-image-understanding-design.md)。

**Goal:** 让用户上传图片后直接问答,图片作为多模态输入直接进 vision 模型(方案 A);活跃图片在连续追问中保持可见。

**Architecture:** 图片以工作区**路径**穿过 前端→message.content.images→proto.turn_images;worker 调 LLM 前才经沙箱把路径读成 base64 data_uri,填进 OpenAI `content:[{text},{image_url}]`。backend 每轮算"活跃图片"(本轮新图 or 最近活跃图)。

**Tech Stack:** Python(uv workspace, FastAPI, SQLAlchemy, gRPC) + worker(openai SDK) + React/Vite/TS。

---

## Task 1:平台 + BYOK 的 vision 能力标记(config)

**Files:** `services/backend/src/agent_cloud_backend/config.py`(改)· `services/backend/tests/test_config.py`(改)

- 仿 `model_context_windows`(config.py:44)新增 `vision_models: list[str] = ["Kimi-K2.6"]`,加方法 `def is_vision_model(self, model: str) -> bool: return model in self.vision_models`。env JSON 可覆盖(`AGENT_CLOUD_VISION_MODELS='["Kimi-K2.6"]'`)。
- 测试:默认含 Kimi-K2.6;`is_vision_model("Kimi-K2.6")` True、`is_vision_model("DeepSeek-V4-Pro")` False;env 覆盖整体替换。
- **Commit:** `feat(config): 加 vision_models 标记 + is_vision_model()`

## Task 2:read_file 对图片返回友好提示(extract)

**Files:** `packages/common/src/agent_cloud_common/extract.py:50-59`(改)· `packages/common/tests/test_extract.py`(改/建)

- `IMAGE_SUFFIXES = {".png",".jpg",".jpeg",".gif",".webp",".bmp"}`;`extract_text` 在"非文档后缀"分支前先判图片后缀,命中则 `return` 一段提示串(不是 raise):
  `"<{name} 是图片,无法按文本读取。要让模型看图,请在对话里把它作为附件上传(需 vision 模型);read_file 不解析图像像素。>"`
- 测试:`extract_text(图片路径)` 返回含 "图片" 和 "vision" 的提示、**不抛异常**;非图片二进制仍 raise(回归)。
- **Commit:** `feat(extract): read_file 读到图片返回友好提示而非报错`

## Task 3:proto 加 turn_images + 重生成桩 + codec

**Files:** `protos/agent_cloud/v1/worker.proto`(改)· 重生成 `packages/common/src/agent_cloud/v1/worker_pb2.py*` · `packages/common/src/agent_cloud_common/codec.py`(查)· `packages/common/tests/test_codec.py`(改)

- `RunTurnRequest`(worker.proto:78-92)加 `repeated string turn_images = 13;`(取下一个未用 field number,实际改时核对)。
- `bash scripts/gen_protos.sh` 重生成桩。
- codec.py:`RunTurnRequest` 的构造/解析若集中在某处,带上 turn_images;若 worker server 直接读 `request.turn_images` 则 codec 无需改(核对 codec.py 是否覆盖 RunTurnRequest)。
- 测试:构造带 turn_images 的 RunTurnRequest → 序列化往返 → 字段保真。
- **Commit:** `feat(proto): RunTurnRequest 加 turn_images(图片工作区路径)`

## Task 4:Message.images + worker 多模态 content 构造(核心)

**Files:** `packages/common/src/agent_cloud_common/types.py:27-35`(改 Message)· `services/worker/src/agent_cloud_worker/openai_provider.py:133-166`(改 to_openai_messages)· `services/worker/tests/test_openai_mapping.py`(改)

- `Message` 加 `images: list[str] = field(default_factory=list)`(承载 **data_uri 字符串**;领域内统一,读图在 Task 5 完成后填)。
- `to_openai_messages` user 分支(openai_provider.py:138-139)改为:
  ```python
  if m.role == Role.USER:
      if m.images:
          parts = [{"type": "text", "text": m.text}] if m.text else []
          parts += [{"type": "image_url", "image_url": {"url": u}} for u in m.images]
          out.append({"role": "user", "content": parts})
      else:
          out.append({"role": "user", "content": m.text})
  ```
- 测试:`Message(role=USER, text="什么图", images=["data:image/png;base64,AAA"])` → content 为 list,含 text part + image_url part;无 images → content 为纯 str(回归)。
- **Commit:** `feat(worker): Message 带 images,to_openai_messages 输出多模态 content`

## Task 5:worker loop 经沙箱读图 → data_uri

**Files:** `services/worker/src/agent_cloud_worker/loop.py:64,83,134`(改 run_turn 签名 + 构造 Message)· 复用 `image_gen.py` 的 `run_read_binary`+`_to_data_uri`(抽公用或直接调)· `services/worker/tests/test_loop.py`(改)

- `run_turn(..., turn_images: list[str] = [])`;构造当前 user `Message` 前,对每个路径经沙箱 `run_read_binary` 读 bytes → `_to_data_uri(bytes, mime)`(mime 按后缀)→ 收集成 `data_uris`;`Message(role=Role.USER, text=user_message, images=data_uris)`。
- 读图失败(沙箱报错/路径不存在):该图位置跳过并在 text 末尾追加 `"[图片 {path} 读取失败]"`,不中断回合。
- `image_gen.py` 的 `_to_data_uri`/`run_read_binary` 若是模块私有,抽到一个共用工具函数(如 `worker/images.py`)供两处复用(DRY)。
- 测试:mock 沙箱 `run_read_binary` 返回固定 bytes,`run_turn(turn_images=["upload/a.png"])` → 构造的 user Message.images 为对应 data_uri;读图抛错 → images 跳过 + text 带失败标记、回合继续。
- **Commit:** `feat(worker): loop 把 turn_images 经沙箱读成 data_uri 注入 Message`

## Task 6:backend — TurnRequest images + 持久化 + assemble 活跃图片

**Files:** `services/backend/src/agent_cloud_backend/schemas/turn.py`(加 images)· `api/turn.py:99-156`(持久化 content.images + 透传 + _reassemble)· `turn/messages.py:25-45`(content↔images)· `turn/assemble.py:84-85`(算活跃图片填 turn_images)· 相关测试 `test_turn_endpoint.py`/`test_assemble.py`

- `TurnRequest` 加 `images: list[str] = []`(工作区相对路径)。
- 持久化:user 消息 `content` 加 `"images": body.images`(messages.py 的 common↔content 两向带上)。
- **活跃图片计算**(assemble.py 新函数 `active_images(history, current_images) -> list[str]`):`current_images` 非空 → 返回它;否则**从 history 末尾向前**找第一条 `role==user 且 content.images 非空` 的消息,返回其 images;都没有 → `[]`。填进 `RunTurnRequest(turn_images=active_images(...))`。
- `turn.py` 把 `body.images` 透传给 assemble(含重试 `_reassemble`)。
- 测试:① TurnRequest.images 存进 message.content.images 并读回;② active_images:本轮有图→本轮;本轮无图、历史有图→最近那条;都无→空;③ 端点冒烟:带 images 的 turn 请求,worker 收到的 RunTurnRequest.turn_images 正确(mock worker)。
- **Commit:** `feat(backend): turn 携带图片 + assemble 算活跃图片填 turn_images`

## Task 7:前端 — 结构化发图 + vision 标记 + 路由提示 + BYOK 勾选

**Files:** `frontend/src/components/Composer.tsx`(图片走结构化 images、路由提示)· `frontend/src/api/client.ts`(TurnRequest images)· `frontend/src/models.ts`+`components/model/useModelOptions.ts`(vision 标志)· `services/backend/.../api/platform.py`(/platform/models 下发 vision)· `models/provider_credential.py`+`schemas`+`components/settings/KeysPanel.tsx`(BYOK vision 勾选)· 对应 `.test.tsx`

- Composer `send()`:把 attachments 按 `IMG_EXT` 拆成 `images:string[]`(结构化,单独传)与非图片(仍走原文本块 `read_file` 提示);`onSend`/`sendTurn` 带 `images`。
- vision 标志:`ProviderOption.models` 从 `string[]` 升级为 `{name:string; vision:boolean}[]`(或并行一个 `visionModels:Set`);平台经 `/platform/models` 返回 `{models, vision_models}`;BYOK 的 vision 来自凭据。
- 路由提示:Composer 在 `images.length>0 && !currentModelVision` 时禁用发送 + 提示"当前模型不支持图片,切到 Kimi-K2.6",给快捷切换(复用 ModelMenu)。
- BYOK 勾选:`provider_credential.models` 元素允许 `{name, vision?}`(向后兼容纯字符串:`typeof m==="string"?{name:m,vision:false}:m`);KeysPanel 每个模型加 vision 勾选;schema/CRUD 同步。
- 测试:Composer 图片进 images、非图片进文本;有图+非 vision 模型→发送禁用+提示;有图+vision→可发;useModelOptions 正确标 vision;KeysPanel vision 勾选往返。
- **Commit:**(可拆 2 个)`feat(frontend): 结构化发送图片 + vision 模型路由提示` / `feat(byok): 凭据模型支持 vision 勾选`

## Task 8:端到端联调

**Files:**(无新增,验证为主)

- docker provisioner 起真沙箱;配一个 vision 模型(平台 Kimi 或 BYOK);走完整流程:上传图 → 选 vision 模型 → 问"图里有什么" → 模型看图回答 → 追问细节(不传新图)→ 仍答得准(活跃图片生效)。
- 验证非 vision 模型 + 图 → 前端拦截提示;读图失败路径 → 回合不崩。
- 全三套回归(backend / worker / frontend)全绿。
- **Commit:**(如有联调修复)`fix(image): 端到端联调修复`

---

## Self-review(spec 覆盖核对)

- 方案 A 直传 → Task 4/5(content parts + 读图)✓
- 提示切换路由 → Task 7 ✓
- 活跃图片回灌 → Task 6 active_images + spec「活跃图片生命周期」✓
- vision 标记(平台+BYOK)→ Task 1 + Task 7 ✓
- read_file 图片兜底 → Task 2 ✓
- proto 带图(传路径避 32MiB)→ Task 3 ✓
- 错误处理(读图失败不崩)→ Task 5 ✓
- 释放(压缩边界)→ Task 6 active_images 只扫未压缩 history(压缩后旧消息已折叠成摘要,不含 images)✓

类型一致性:`turn_images`(proto)↔ `Message.images`(data_uri)↔ `TurnRequest.images`/`content.images`(路径)↔ `active_images()` 命名贯穿一致。
