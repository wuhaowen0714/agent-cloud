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
- `openai_provider.py`:`OpenAIProvider.__init__` 加可选 `ttft: TtftConfig | None`(默认 None → 不套动态超时,向后兼容)。`stream()`/`complete()` 在已算好的 `kwargs["messages"]` 上算 budget,`has_images = any(m.images for m in request.messages)`,设 `kwargs["timeout"]=budget`,并 `logger.info` 出 `model/images/payload_chars/budget`(可观测,供上线后调参)。
- `factory.py`:从 `settings` 构造 `TtftConfig` 传给 `OpenAIProvider`。

不碰:keepwarm(独立 120s 心跳);错误处理与 SDK `max_retries=3` 重试链(budget 超时即复用现有重试)。

## 测试

- `test_ttft.py`:`payload_text_len`(纯文本 / 含图跳过 base64 / tool_calls 计入);`ttft_budget`(两档基线、长度加成线性、floor/ceil 夹逼边界)。
- `test_openai_provider.py`:stream + complete 传出预期 `timeout`(用 `captured` 断言);不传 `ttft` 时**不**设 timeout(向后兼容)。
- `test_factory.py`:**wiring 测试**——factory 构造的 provider 拿到 `TtftConfig`,且改 settings 的 ttft 值后 provider 用新值(防"漏传参→配置静默失效"的同类回归)。
- 全回归:worker 套件。

## 取舍

- 治标,不治本:根因在 sophnet 上游冷启,不可控。本特性只缩短撞冷启时的等待。
- per-request `timeout` 流式下也作用于"等后续 chunk",但正常 chunk 间隔 <1s,远不撞预算;长输出只要持续吐字不被误杀。只有首字节(冷启)会撞——正是目标。
- 参数默认保守(ceil≤45 不比现状差),配 debug log 观察真实 payload 分布后再调死。
