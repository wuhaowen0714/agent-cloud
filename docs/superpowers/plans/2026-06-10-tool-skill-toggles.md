# TopBar 工具/技能开关 + 内置技能开箱即用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TopBar 即点即存的 tool/skill 启用开关;内置技能(skill-creator)自动安装并对 agent 默认启用,砍掉手动安装界面。

**Architecture:** 后端:`ensure_builtin_skills`(幂等补装)挂 `GET /skills` 与注册;`enable_builtin_skills`(启用全部 registry 来源技能)挂注册种子 main 与 `POST /agent-configs`。前端:TopBar 两按钮 + portal popover(RowMenu 模式),工具走 `patchAgent(enabled_tools)`(空=全部语义沿用),技能走 `setAgentSkills` 全量 PUT,乐观更新。SkillsPanel 删 registry 安装段,内置不可删。

**Tech Stack:** FastAPI + pytest(testcontainers);React19 + React Query + vitest。

参考 spec:`docs/superpowers/specs/2026-06-10-tool-skill-toggles-design.md`

---

## Task W1: registry 清理(删 example-greeting)+ 测试改造

**Files:**
- Delete: `services/backend/src/agent_cloud_backend/skill_registry/example-greeting/`
- Modify: `services/backend/tests/test_skills_api.py`、`tests/test_skill_turn_e2e.py`(`example-greeting` → `skill-creator`;`test_skill_manifest.py` 的字符串 fixture 自包含,不动)

- [ ] 删目录;两个测试文件里安装名与断言路径(`.skills/example-greeting/` → `.skills/skill-creator/`)全部替换;若有 conftest/fixture 引用一并改。
- [ ] Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skills_api.py tests/test_skill_turn_e2e.py tests/test_skill_manifest.py -q` → 全 PASS
- [ ] 提交 `chore(backend): drop example-greeting from skill registry`

## Task W2: ensure_builtin_skills + GET /skills 自动补装(TDD)

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/skills/service.py`
- Modify: `services/backend/src/agent_cloud_backend/api/skills.py`(GET "" 端点)
- Test: `services/backend/tests/test_skills_api.py`

- [ ] **失败测试**(test_skills_api.py 追加;沿用文件内既有 client/注册 fixture 风格):

```python
async def test_list_skills_auto_installs_builtins(client):
    # 新用户首次 GET /skills:内置技能(skill-creator)被自动补装
    r = await client.get("/skills")
    assert r.status_code == 200
    assert [s["name"] for s in r.json()] == ["skill-creator"]
    assert r.json()[0]["source"] == "registry"


async def test_list_skills_ensure_is_idempotent(client):
    await client.get("/skills")
    r = await client.get("/skills")
    assert [s["name"] for s in r.json()] == ["skill-creator"]  # 不重复安装


async def test_install_after_auto_ensure_conflicts(client):
    await client.get("/skills")
    r = await client.post("/skills/install", json={"name": "skill-creator"})
    assert r.status_code == 409  # 已被 ensure 装好
```

- [ ] 确认失败(`ensure_builtin_skills` 不存在 / GET 不补装)
- [ ] **实现** — service.py 追加:

```python
async def ensure_builtin_skills(
    *,
    user_id: uuid.UUID,
    registry_root: Path,
    repo: SkillRepository,
    store: ObjectStore,
) -> list[Skill]:
    """把 registry 里该用户缺失的内置技能补装(幂等)。返回本次新装的。

    GET /skills 与注册时调用:无缺失时只有一次目录扫描 + 名字比对,零写入。
    目录名预筛、manifest.name 终判;并发 ensure 撞 ValueError(已装)视为达成。
    """
    if not registry_root.exists():
        return []
    installed = {s.name for s in await repo.list_by_user(user_id)}
    out: list[Skill] = []
    for p in sorted(registry_root.iterdir()):
        if not p.is_dir() or not (p / "SKILL.md").is_file() or p.name in installed:
            continue
        try:
            out.append(await install_skill_from_dir(
                user_id=user_id, src_dir=p, source="registry", repo=repo, store=store,
            ))
        except ValueError:
            pass
    return out
```

skills.py 的 `list_skills` 改为(已有 deps 导入):

```python
@router.get("", response_model=list[SkillRead])
async def list_skills(
    session: AsyncSession = Depends(get_session),
    store: ObjectStore = Depends(get_object_store),
    registry_root: Path = Depends(get_skill_registry_root),
    user: User = Depends(get_current_user),
):
    # 幂等副作用:补装缺失的内置技能 —— 存量用户任何一次 UI 加载即收敛(开箱即用)。
    repo = SkillRepository(session)
    if await ensure_builtin_skills(
        user_id=user.id, registry_root=registry_root, repo=repo, store=store
    ):
        await session.commit()
    return await repo.list_by_user(user.id)
```

- [ ] Run: skills 相关三件 + 全量 backend → 全 PASS(既有「先 GET 再 install」的测试若被 409 影响,按新语义修整)
- [ ] 提交 `feat(backend): auto-install builtin skills on GET /skills (idempotent ensure)`

## Task W3: 注册 / 新建 agent 默认启用内置技能(TDD)

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/skills/service.py`(enable 助手)
- Modify: `services/backend/src/agent_cloud_backend/api/auth.py`(register)
- Modify: `services/backend/src/agent_cloud_backend/api/agent_configs.py`(POST)
- Test: `services/backend/tests/test_skills_api.py`(或 agent_skills 既有测试文件)

- [ ] **失败测试**:

```python
async def test_register_enables_builtins_on_main_agent(client):
    agents = (await client.get("/agent-configs")).json()
    main = next(a for a in agents if a["name"] == "main")
    r = await client.get(f"/agent-configs/{main['id']}/skills")
    assert [s["name"] for s in r.json()] == ["skill-creator"]


async def test_new_agent_gets_builtins_enabled(client):
    r = await client.post("/agent-configs", json={"name": "a2", "model": "m", "provider": "openai"})
    agent_id = r.json()["id"]
    enabled = (await client.get(f"/agent-configs/{agent_id}/skills")).json()
    assert [s["name"] for s in enabled] == ["skill-creator"]
```

- [ ] 确认失败(启用集为空)
- [ ] **实现** — service.py 加(导入 `AgentSkillEnableRepository`):

```python
async def enable_builtin_skills(
    *,
    agent_config_id: uuid.UUID,
    user_id: uuid.UUID,
    repo: SkillRepository,
    enable_repo: AgentSkillEnableRepository,
) -> None:
    """把用户已装的全部内置(registry 来源)技能启用到该 agent(新 agent 的默认)。"""
    ids = [s.id for s in await repo.list_by_user(user_id) if s.source == "registry"]
    if ids:
        await enable_repo.replace_enabled_set(agent_config_id, ids)
```

auth.py register(种子 session 之后、`return await _issue(...)` 之前;导入 service/deps/repo):

```python
    # 内置技能开箱即用:补装 + 对种子 main 默认启用(与 user 同事务)
    skill_repo = SkillRepository(db)
    await ensure_builtin_skills(
        user_id=user.id, registry_root=get_skill_registry_root(),
        repo=skill_repo, store=get_object_store(),
    )
    await enable_builtin_skills(
        agent_config_id=agent.id, user_id=user.id,
        repo=skill_repo, enable_repo=AgentSkillEnableRepository(db),
    )
```

agent_configs.py `create_agent_config`(create 之后、commit 之前;同样 ensure——防止从未 GET /skills 的路径建出无内置技能的 agent):

```python
    skill_repo = SkillRepository(session)
    await ensure_builtin_skills(
        user_id=user.id, registry_root=get_skill_registry_root(),
        repo=skill_repo, store=get_object_store(),
    )
    await enable_builtin_skills(
        agent_config_id=agent.id, user_id=user.id,
        repo=skill_repo, enable_repo=AgentSkillEnableRepository(session),
    )
```

- [ ] Run: backend 全量(`TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m "not docker" -q`)→ 全 PASS(注册种子改变会影响断言「agent 无技能」的既有测试,按新语义修整)+ `uv run ruff check .`
- [ ] 提交 `feat(backend): builtin skills enabled by default on main + new agents`

## Task W4: SkillsPanel 简化 + client 清理(TDD)

**Files:**
- Modify: `frontend/src/components/settings/SkillsPanel.tsx`
- Modify: `frontend/src/api/client.ts`(删 `listRegistry`/`installSkill`)
- Test: `frontend/src/components/settings/SkillsPanel.test.tsx`

- [ ] **失败测试**(改造既有文件):无「从 registry 安装」文案;`source: "registry"` 的行无「删除」按钮;`source: "upload"` 的行有
- [ ] **实现**:SkillsPanel 删 registry query、install mutation、pick state、整个安装 SettingGroup;删除按钮包 `{sk.source !== "registry" && (...)}`(内置不可删——前端已无安装入口);client.ts 删两个函数(grep 确认无他处引用)
- [ ] Run: `cd frontend && npx vitest run && npm run lint` → 全 PASS
- [ ] 提交 `feat(frontend): SkillsPanel — builtins are managed, drop manual registry install`

## Task W5: TopBar 工具/技能 popover(TDD)

**Files:**
- Create: `frontend/src/components/toggles/TogglePopover.tsx`(portal 壳:fixed 定位到锚点下方、Esc/点外关闭——镜像 RowMenu 的 portal 手法)
- Create: `frontend/src/components/toggles/ToolsMenu.tsx`、`SkillsMenu.tsx`
- Modify: `frontend/src/components/TopBar.tsx`(两按钮 + 开合 state)
- Test: `frontend/src/components/toggles/ToolsMenu.test.tsx`、`SkillsMenu.test.tsx`、`TopBar.test.tsx` 增补

- [ ] **失败测试**:
  - ToolsMenu:`enabled_tools: []` → 5 个 Switch 全开;关掉一个 → `patchAgent` 收到其余 4 个的列表;再开回 → 收到 `[]`(全勾规范化);
  - SkillsMenu:列出 `listSkills` 全量,checked = `getAgentSkills` 集合;切换 → `setAgentSkills` 收到新 id 集合;
  - TopBar:有 agent 时两按钮可点,点击出现 popover(`getByText("工具")`/`getByText("技能")` 面板标题);无 agent 时 disabled。
- [ ] **实现**:
  - `TogglePopover`:props `{ anchor: HTMLElement; title: string; onClose: () => void; children }`;`createPortal` 到 body,`position: fixed`,锚点 `getBoundingClientRect()` 右对齐下方 4px;`useEffect` 挂 Esc + mousedown-outside;
  - `ToolsMenu`:行 = `BUILTIN_TOOLS`,`Switch` checked 来自 `enabledToChecked(agent.enabled_tools)`;mutation `api.patchAgent(agent.id, { enabled_tools })`,乐观:`onMutate` 时 `setQueryData(["agents", userId])` 翻本地、快照回滚于 `onError`、`onSettled` invalidate;
  - `SkillsMenu`:`["skills", userId]` + `["agentSkills", agentId]` 两查询;mutation `api.setAgentSkills`,乐观同上(key `["agentSkills", agentId]`);空态文案「技能池为空」;
  - TopBar:`Wrench`/`Sparkles` 按钮(样式同 Folder),`open: "tools" | "skills" | null` state,disabled 当 `!agent`(title「先选择 agent」)。
- [ ] Run: `cd frontend && npx vitest run && npm run lint` → 全 PASS
- [ ] 提交 `feat(frontend): TopBar tool/skill toggle popovers (per-agent, instant save)`

## Task W6: 回归 + Fable 5 对抗审查 + PR

- [ ] backend 全量 + ruff;前端全量 + lint
- [ ] Fable 5 对抗审查(diff 内联)重点:GET 副作用的幂等与并发(同用户两请求同时 ensure)、注册事务边界(_issue 前未 commit 的种子链)、409 路径回归、SkillsPanel 删除按钮条件、popover 乐观更新回滚、TopBar disabled 语义
- [ ] 修复 → push → `gh pr create`(标题 `feat: topbar tool/skill toggles + builtin skills out of the box`)→ CI 绿 → 等合并指令
