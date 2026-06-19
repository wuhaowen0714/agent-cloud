# 图片理解(多模态)设计

> 状态:已与用户确认核心决策,待 review → writing-plans。日期 2026-06-19。

## 目标

让用户上传图片后直接问答,图片**作为多模态输入直接进多模态模型**(如 Kimi-K2.6),模型亲眼看图作答(方案 A)。不走"先把图转文字描述再用文本模型"的有损方案(方案 B)。

## 设计决策(已确认)

| 决策 | 选择 | 理由 |
|---|---|---|
| 图片如何进模型 | **方案 A:直接进多模态模型** | 多轮追问是常态;转文本有损 + 盲转,后续文本模型看不见原图,追问细节(OCR 数字/布局/颜色/图表数据点)答不准。业界(GPT-4V/Claude/Gemini)统一做法。 |
| 选了纯文本模型却传图 | **前端提示切到 vision 模型** | 尊重「会话级模型选择」,不偷偷换模型(避免成本/风格被静默改变)。 |
| 历史图片回灌 | **保留最近上传的图(追问都可见)** | 围绕一张图的连续追问,模型每轮都能回看原图(图片问答应有的体验);换新图替换、历史压缩折叠则释放。代价:活跃期间每轮带图、用多模态模型,token 较高(用户知情选择)。 |
| 范围 | **完整版**(回灌除外) | vision 标记(含 BYOK)、前端路由提示、端到端图片通道、`read_file` 读图兜底都做;唯历史回灌按"只发当轮"。 |

## 核心架构:图片以「工作区路径」穿行,worker 调 LLM 前才读成图

```
前端 images:[路径]  →  message.content.images  →  proto RunTurnRequest.user_images
                                                              │
                          worker 调 LLM 前:路径 ──经沙箱 ReadBinary──► base64 data_uri
                                                              │
                          OpenAI content:[{type:text}, {type:image_url}]  →  多模态模型看到图
```

**为什么传路径不传字节**:worker 已有"经沙箱把工作区图片读成 base64"的成熟能力(`edit_image` 在用:`image_gen.py` 的 `run_read_binary` + `_to_data_uri`)。图片全程只传**工作区相对路径(字符串)**,只在 worker 最后一步(调 LLM 前)才读成 data_uri。好处:
- proto / message 表只存轻量路径,**避开 gRPC 32MiB 上限**(`grpc_limits.py`);
- 复用已验证的沙箱读图通道,不新造轮子;
- worker→OpenAI 是 HTTP(不受 gRPC 限),data_uri 在这一跳才出现。

## 端到端数据流(逐层改造点)

### 1. 模型 vision 能力标记(`config.py`)
- 新增 `vision_models: list[str]`,**照抄现有 `model_context_windows` 模式**(按模型名挂属性、env JSON 可覆盖)。平台侧 Kimi-K2.6 列入。
- `api/platform.py` 的 `/platform/models` 把 vision 标记一并下发前端。
- **BYOK 模型**:`provider_credential.models` 目前是纯字符串数组(`provider_credential.py:22`)。扩成可选结构 `{name: str, vision?: bool}`(向后兼容纯字符串),让用户给自己的多模态 BYOK 模型打勾。Keys 设置页加一个 vision 勾选。

### 2. 前端:结构化发送图片 + 路由提示
- `Composer.tsx` 已有结构化 `attachments:{path,name}[]`(`:38`)。发送时**按扩展名(`IMG_EXT`)分流**:图片走新的结构化 `images:[路径]` 字段;非图片附件仍走原"路径文本 + read_file"路径(不破坏现有行为)。
- `onSend` 签名 / `TurnRequest` schema 加 `images?: string[]`。
- **路由提示**:`useModelOptions` 带上每个 model 的 `vision` 标志;Composer 在「有图 + 当前会话 model 不支持 vision」时,禁用发送并提示"当前模型不支持图片,切换到 Kimi-K2.6 再发"(给一个快捷切换入口,复用现有 ModelMenu)。
- 缩略图回显(`UserAttachments.tsx`)已具备,沿用。

### 3. message 表承载图片引用
- user 消息 `content` JSONB 加 `images: ["upload/cat.png", ...]`(**复用 JSONB,不加列**;`models/message.py` 不动)。
- `turn.py` 持久化、`turn/messages.py` 的 `common_to_content`/`orm_to_common` 同步带上 images。

### 4. proto:RunTurnRequest 加图片路径(本回合活跃图)
- `worker.proto` 给 `RunTurnRequest` 加 `repeated string turn_images = N;`(**本回合要发给模型的图片**工作区路径——可能是本轮新上传,也可能是 backend 回填的"活跃图片")。
- **历史 `Msg` 不加图字段**——图片不按历史逐条回灌;由 backend 每轮算出"活跃图片"统一放进 `turn_images`,worker 照单发给本次请求即可,无需理解"活跃"语义,proto 历史保持轻量。
- 重新生成 `worker_pb2.py` 桩(`scripts/gen_protos.sh`);同步 `codec.py`、`assemble.py`。

### 5. backend assemble:当前轮图片填进 proto
- `assemble.py` 计算**本回合活跃图片**填进 `turn_images`:本轮 `body.images` 非空 → 用本轮(新上传,替换活跃);为空 → 回退到**会话里最近一条未被压缩、含 images 的 user 消息**的图片(延续追问)。历史 `Msg` 仍不带图。
- 入口 `turn.py` 把 `body.images` 透传(含重试 `_reassemble`)。

### 6. worker:读图 + 多模态 content 构造(核心)
- `packages/common/types.py` 的 `Message` 加 `images: list[str]`(承载 data_uri 或 (mime,bytes);领域内统一)。
- `loop.py` `run_turn(..., user_images: list[str])`:构造当前 `Message(role=USER, ...)` **前**,先**经沙箱 `run_read_binary` 把每个路径读成 bytes → data_uri**(async),存进 `Message.images`。
- `openai_provider.py` `to_openai_messages` 的 user 分支:`Message.images` 非空时输出
  `content=[{"type":"text","text":m.text}, {"type":"image_url","image_url":{"url": data_uri}}, ...]`;为空时维持纯字符串(不影响现有文本路径)。

### 7. `read_file` 图片兜底(`extract.py`)
- 现在 `extract_text` 对图片直接抛 "looks binary" 错(`extract.py:50-59`)。改为返回友好提示,如:"这是图片文件(png/jpg);要让我看图请直接在对话里把它作为附件上传(需 vision 模型),`read_file` 不解析图像像素。" —— 让 agent 知道正确做法,而非以为文件坏了。

## 活跃图片的生命周期

- **活跃图片** = 最近一次上传、且尚未被历史压缩折叠的图片。
- **延续**:有活跃图片时,后续每轮(即便没传新图)都把它放进 `turn_images` 发给模型 → 追问可见。
- **替换**:用户上传新图 → 新图成为活跃图片。
- **释放**:① 历史压缩把含图消息折叠进摘要后,图不再回灌(摘要是文本,天然边界);②(可选 UI)用户在附件区显式移除当前图片。
- **路由**:有活跃图片的回合都需 vision 模型;当前会话模型不支持则提示切换(同「模型路由」决策)。

## 错误处理与边界

- **图片读取失败**(沙箱读不到/损坏/超大):worker 该图位置回填错误说明,模型据此告知用户;不中断整个回合。
- **BYOK 用户绕过前端校验**带图给不支持 vision 的模型:provider 调用可能报错;worker 捕获→友好错误结果,不崩。
- **图片大小**:单图建议设上限(如 ≤ 10MB,沿用上传 `file_upload_max_bytes`);超大图提示用户压缩。data_uri 仅 worker→OpenAI 这一 HTTP 跳出现,不过 gRPC。
- **非目标**:本期不做服务端 OCR、不做图片生成(已有 `generate_image`/`edit_image`)、不做历史图片回灌(只发当轮)、不做视频/音频。

## 测试策略

- `config`:`vision_models` 标记解析 + env 覆盖。
- proto/codec:`user_images` 序列化往返。
- backend:`TurnRequest.images` 透传、message `content.images` 存取;assemble 计算活跃图片填 `turn_images`(本轮新图 / 回退最近活跃图 / 压缩折叠后不回灌)、历史 Msg 不带图。
- worker:`to_openai_messages` 带 images → 输出 content parts;空 images → 维持纯字符串(回归);`loop` 读图路径→data_uri(mock 沙箱 `run_read_binary`)。
- 前端:Composer 图片走结构化 images、非图片走文本;有图+文本模型→发送禁用+提示;有图+vision 模型→正常发送。
- `extract_text` 图片→友好提示(非报错)。

## 实现顺序(writing-plans 细化)

按"自底向上、每步可独立测"的顺序,改动量小→大:
1. `config.vision_models` + 解析(纯加法)。
2. `extract_text` 图片兜底(独立小改)。
3. proto 加 `turn_images` + 重生成桩 + codec(契约先行)。
4. common `Message.images` + worker `to_openai_messages` 多模态 content(核心,纯函数易测)。
5. worker `loop` 经沙箱读图→data_uri。
6. backend:TurnRequest images + 持久化 + assemble 填 proto。
7. 前端:结构化发送 + vision 标记下发 + 路由提示 + Keys 页 BYOK vision 勾选。
8. 端到端联调(docker provisioner + 真多模态模型)。
