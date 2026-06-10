# 模型切换器(仿 Claude Code)设计

**日期:** 2026-06-10
**状态:** 设计已批准,待写实现计划

## 目标

仿 Claude Code 的模型选单:composer 区一个当前模型 chip,点开向上弹出模型列表(勾选当前项),即点即切;预设模型 + 用户自定义模型(存后端、跨设备);创建 agent 不再填模型,预设 `DeepSeek-V4-Pro`。设置页的模型字段与 composer 共用同一个选单组件,斜杠 `/model` 共用同一个选项源。

已确认的三个决策:
1. 自定义模型**后端按用户存**(新表 + CRUD,跨设备)。
2. 设置页 Agent 编辑表单的「模型」字段**换成同一个选单**。
3. 本特性在合并 UI 重设计(PR #4)后的 main 上的独立分支开发。

## 非目标(YAGNI)

- 数字 / ⌘ 键盘快捷键、Fast mode 一类的附属开关。
- 模型元数据(价格、上下文长度、能力标签)。
- 按 provider 联动过滤模型(model 只是字符串,不碰 provider/key)。
- 修改后端 AgentConfig 的 model 语义(仍是 agent 上的必填字符串)。

---

## 1. 数据层(后端)

### 表 `user_models`(+ Alembic 迁移)

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | uuid PK | |
| `user_id` | uuid FK→users.id, `ondelete=CASCADE`, index | 归属用户 |
| `model` | text, not null | 模型名(存前 trim) |
| `created_at` | timestamptz | TimestampMixin |

约束:**UNIQUE(user_id, model)**。

### API(`/models`,全部限当前用户,经 `get_current_user`)

- `GET /models` → `UserModelRead[]`,按 `created_at` 升序。
- `POST /models {model}` → **201 + 行**;`model` trim 后非空、≤200 字符,否则 422;**重复时幂等返回已有行**(同样 201,前端零分支)。
- `DELETE /models/{id}` → 204;行不存在或不属本人 → **404**(与全站归属语义一致,不泄漏存在性)。

实现:model `UserModel` + repository(list_by_user / get_or_create / delete owned)+ schemas(`UserModelCreate`/`UserModelRead`)+ router 注册进 app。

## 2. 前端共享源

### `src/models.ts`(纯常量/纯函数)

```ts
export const PRESET_MODELS = ["DeepSeek-V4-Pro", "DeepSeek-V4-Flash", "GLM-5.1"]
export const DEFAULT_MODEL = "DeepSeek-V4-Pro"
```

### `api/client.ts`

`listModels()` / `addModel(model)` / `deleteModel(id)`,类型 `UserModel { id, model, created_at }`(进 `types.ts`)。

### `useModelOptions()` hook(`src/components/model/useModelOptions.ts`)

- query `["userModels", userId]` → 自定义列表;复用 `["agents", userId]` 缓存取在用模型。
- 返回:
  - `options: { model: string; custom?: UserModel }[]` —— **去重合并,顺序:预设 → 在用(未在前者出现的) → 自定义(未在前者出现的)**;`custom` 字段仅自定义条目携带(供删除)。
  - `addModel(model): Promise<string>`(POST → 失效 userModels → 返回 trim 后的模型名)。
  - `removeModel(id): Promise<void>`(DELETE → 失效 userModels)。
- 去重复用 `dedupeModels` 思路(trim + Set 保序)。

### 删除语义

- 只有**自定义条目**可删(预设/在用条目无删除按钮)。
- 删除一个仍被某 agent 使用的自定义模型 → 它会从「在用」派生回列表;不影响任何 agent 的 `model` 字段。

## 3. `ModelMenu` 组件(`src/components/model/ModelMenu.tsx`)

**受控纯组件**:自己不 patch agent,选择行为由调用方决定——这使设置页(改本地草稿、保存才生效)与 composer(立即生效)可共用。

props:

```ts
{
  value: string                       // 当前模型
  onChange: (model: string) => void   // 选中/添加即回调
  variant?: "chip" | "field"          // 触发器形态,默认 "field"
}
```

- **triggers**:
  - `field`(设置页):沿用 `SelectMenu` 的填充式按钮外观(rounded-xl border bg-slate-100/70 …)。
  - `chip`(composer):ghost 小字 chip——`模型名 + ChevronDown`,`text-xs text-slate-500`,hover 轻底色。
- **浮层**(`z-30 rounded-xl border bg-white p-1.5 shadow-pop`,`max-h-72 overflow-auto`;**方向与 SelectMenu 同款判定**——默认向下,下方空间不足且上方更宽裕则向上;composer 的 chip 贴屏幕底部,自然总是向上):
  - 模型行:`role="option"`,当前项左侧 lucide `Check`(brand-600);点击 → `onChange(model)` + 关闭。
  - **自定义条目** hover 露出右侧删除 `X`(`aria-label="删除 <model>"`),点击只删条目、不触发选中、不关浮层。
  - 底部分隔线下「**＋ 添加模型…**」行:点击变行内 `<input>`(autoFocus),Enter 提交 → `addModel` → **`onChange(新模型)`(添加即选中)** + 关闭;Esc 取消回列表;空串忽略。
- **交互范式**(沿用 SelectMenu):`aria-haspopup/expanded`、`listbox/option` + `aria-selected`、Esc 关闭回焦触发器、`pointerdown` 点外面收起。

## 4. 接入点(4 处)

1. **Composer**(`components/Composer.tsx`):输入行下方加一条 slim footer(与输入框同宽容器内,`mx-auto max-w-5xl`),**左下角**放 `<ModelMenu variant="chip" value={当前 agent.model} onChange={m => patchAgent(agentId, { model: m }) + 失效 ["agents", userId]} />`。无 agentId 或 agents 缓存未命中时不渲染 chip。切换反馈即 chip 文本变化,不弹 flash。(沿用 `/model` 的语义:持久到当前 agent。)
2. **AgentSettings 编辑表单**:「模型」行 `Input` → `<ModelMenu value={form.model} onChange={(m) => setForm({...form, model: m})} />`——改本地草稿,**点保存才落库**,与表单其它字段一致。
3. **AgentSettings 创建表单**:**去掉模型输入行**(只剩名称/Provider),提交 `createAgent({ name, model: DEFAULT_MODEL, provider })`。
4. **斜杠 `/model`**:`useSlashCommands.modelSuggestions()` 改为 `useModelOptions().options.map(o => o.model)`(预设 ∪ 在用 ∪ 自定义);「应用 '<自由输入>'」兜底保留。

## 5. 测试

**后端 pytest**(`tests/test_models_api.py`):
- GET 空列表;POST 创建后 GET 可见;POST 重复幂等(同一行、不报错);POST 空/超长 422;DELETE 后消失;DELETE 他人/不存在 → 404;用户 A 看不到用户 B 的(隔离)。

**前端 vitest**:
- `useModelOptions` 顺序与去重(预设/在用/自定义合并;自定义带 `custom`)。
- `ModelMenu`:列出选项、勾选当前、点击回调 `onChange`;「添加模型…」流程(输入 + Enter → addModel 被调 → onChange 新值);自定义条目删除调 `deleteModel` 且不触发 onChange。
- `Composer`:渲染模型 chip(显示当前模型);选单选择 → `patchAgent` 被调。
- `AgentSettings`:创建表单**无**模型输入;提交 `createAgent` 带 `model: DEFAULT_MODEL`;编辑表单选单改草稿、保存 patch 带新模型。
- `/model` 建议:含预设 + 自定义(mock 缓存)。

## 6. 受影响文件

**后端(新增)**:`models/user_model.py`、`repositories/user_model.py`、`schemas/user_model.py`、`api/models.py`、迁移 `*_user_models.py`、`tests/test_models_api.py`;**修改**:`main.py`(挂 router)、`models/__init__.py`。

**前端(新增)**:`src/models.ts`、`components/model/ModelMenu.tsx`、`components/model/useModelOptions.ts`(+ 各自测试);**修改**:`types.ts`、`api/client.ts`、`components/Composer.tsx`(footer chip)、`components/settings/AgentSettings.tsx`(编辑行换选单、创建表单去模型)、`components/slash/useSlashCommands.ts`(建议源)、相关测试。
