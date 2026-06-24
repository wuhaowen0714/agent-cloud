# 动态首字节(TTFT)超时 — 设计

## 背景

真实 LLM 请求是流式。worker 的 client 用固定 `openai_timeout_seconds=45s`,流式下它作用于"等下一个 chunk"(含首字节)。idle 后撞 sophnet 上游冷启时,**首字节**迟迟不来,卡满 45s 才超时,openai SDK 才重试——用户感知"卡住不答"。线上实测(2026-06-24 会话 045bf6):用户 09:39 发"你好",第一次调用卡满 45s,SDK 在 01:40:28 重试,第二次撞 keepwarm 焐热的路由秒回,总等待 ~49s。

根因在 sophnet 上游冷启(已知,见 keepwarm 注释),客户端治不了根。但可缩短"撞冷启时的等待":把固定 45s 换成**按请求动态算的首字节预算**——纯文本/短上下文快速 fail-fast 重试,多模态/长上下文给足不误杀。

## 计算规则

`budget = clamp(base + length_add, floor, ceil)`,作为 per-request `timeout` 传给 `create()`。

1. **长度 L** = `to_openai_messages(request)` 后的**完整 payload 文本字符数**:system prompt + 全部工具 JSON schema(含 tool_calls 的 name/arguments)+ 历史 + 用户消息文本。**图片 base64/data_uri 不计入**(不反映 prefill 难度,且体积巨大会扭曲长度)。
2. **基线 base**(两档):纯文本 → `text_base`(默认 12s);含图 → `multimodal_base`(默认 25s)。
3. **长度加成** = `min(L / chars_per_second, length_cap)`,即每 `chars_per_second`(默认 2000)字符 +1s,封顶 `length_cap`(默认 20s)。
4. **夹逼**:`clamp(base + length_add, floor=10s, ceil=45s)`。`ceil` 不超 `openai_timeout_seconds`,保证最坏不比固定超时差;`floor` 防过激误杀。

**算例**(假设 system+tools 固定底 ≈ 12k 字符):

| 请求 | L | base | length_add | budget |
|---|---|---|---|---|
| "你好"(新会话) | ~12k | 12 | 6 | **18s** |
| 纯文本长会话 | ~60k | 12 | 20(cap) | **32s** |
| 多模态短 | ~12k | 25 | 6 | **31s** |
| 多模态+长上下文 | ~60k | 25 | 20 | **45s**(触顶) |

"你好"实际 18s(非 12s)——system+tools 把 L 撑起来了。撞冷启时 18s fail-fast 重试,总等待 ~49s→~20s;正常请求首字节(热路由 1–7s)远在预算内,不误杀。

## 实现

新模块 `ttft.py`(纯函数,单一职责,独立可测):
- `TtftConfig`(frozen dataclass):六个参数,从 `WorkerSettings` 提取后注入 provider。
- `payload_text_len(messages) -> int`:遍历 `to_openai_messages` 输出累加文本字符,`content` 为 list(content parts)时只数 `type==text`、跳过 `image_url`;tool_calls 的 name/arguments 计入。
- `ttft_budget(messages, has_images, cfg) -> tuple[float, int]`:返回 (budget 秒, payload 字符数)。

改动点:
- `config.py`:+6 个 `ttft_*` 配置项(env 可覆盖),紧邻 `openai_timeout_seconds`。
- `openai_provider.py`:`OpenAIProvider.__init__` 加可选 `ttft: TtftConfig | None`(默认 None → 不套,向后兼容)。**仅 `stream()`** 在已算好的 `kwargs["messages"]` 上算 budget、设 `kwargs["timeout"]=budget`、`logger.info` 出 `model/images/payload_chars/budget`(可观测,供调参)。`has_images = any(m.images for m in request.messages)`——历史消息经 `codec.msg_from_proto` **不回填 images**,故恰好只在当前回合有新上传图时为真(若将来 codec 改成回填,text-only 跟进回合会误套多模态档,需同步调整)。
- **`complete()`(非流式)不套 TTFT**:非流式 timeout 作用于整次生成(无首字节/chunk 之分),套了会把 `RunTurn`(`loop.run_turn`,可生成至 `request_max_tokens`≈32k)等正常长输出误杀成 INTERNAL。
- 长度计入 `reasoning_content`(思考端点回传、上行算入 prefill 负担)。
- `factory.py`:从 `settings` 构造 `TtftConfig` 传给 `OpenAIProvider`(含 wiring 测试,防漏传参静默失效)。

不碰:keepwarm(独立 120s 心跳);错误处理与 SDK `max_retries=3` 重试链(budget 超时即复用现有重试)。

## 测试

- `test_ttft.py`:`payload_text_len`(纯文本 / 含图跳过 base64 / tool_calls 计入);`ttft_budget`(两档基线、长度加成线性、floor/ceil 夹逼边界)。
- `test_openai_provider.py`:stream + complete 传出预期 `timeout`(用 `captured` 断言);不传 `ttft` 时**不**设 timeout(向后兼容)。
- `test_factory.py`:**wiring 测试**——factory 构造的 provider 拿到 `TtftConfig`,且改 settings 的 ttft 值后 provider 用新值(防"漏传参→配置静默失效"的同类回归)。
- 全回归:worker 套件。

## 取舍

- 治标,不治本:根因在 sophnet 上游冷启,不可控。本特性只缩短撞冷启时的等待。
- per-request `timeout` 流式下是 **per-chunk read 截断**(每收到一个 chunk 即重置),不是整流总时长(已逐层核 openai→httpx→httpcore→anyio)——长输出只要相邻 chunk 间隔 < budget 就不被误杀。冷启(响应头阶段久不来)落在 SDK 重试窗口内,正是优化目标。
- **已知回归面(接受 + 观察)**:流到一半若上游停顿 > budget,该 read 超时落在 SDK 重试范围**外**(消费阶段),整回合失败(无半成品、需重发)。原固定 45s 对 mid-stream 停顿有 45s 容忍,纯文本档收紧到 ~10–18s。但正常相邻 chunk 间隔 <1s、远不撞,`floor` 给下限容忍;先上线靠 debug log 观察 mid-stream 误杀是否真实出现,再决定是否回调。(根因:裸 float 让 connect/read 同值,无法只收紧首字节而放宽 chunk 间隔。)
- **最坏总时长**:budget 超时即 SDK 重试(每次同 budget),最坏 `(max_retries+1)×budget + 退避`。纯文本短 ≈ 4×12+~3.5 ≈ 52s、多模态 ≈ 4×25 ≈ 103s——连续撞冷的罕见路径并不比原 45×N 短;收益在**常见路径**(第一次撞冷 fail-fast、keepwarm 在退避窗口内焐热、第二次秒回 ≈ 15s,对比原 ~49s)。
- 参数默认保守(ceil≤45,最坏不比现状差),配 debug log 观察真实 payload 分布后再调死。
