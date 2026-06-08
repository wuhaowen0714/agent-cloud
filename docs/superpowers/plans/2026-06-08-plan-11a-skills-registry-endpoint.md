# Plan 11a: Skills Registry Endpoint — Backend

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** `GET /skills/registry` lists the installable built-in skill names, so the settings UI's "install" can be a picker instead of free-text.

**Tech Stack:** FastAPI, pytest. Spec: [2026-06-08-agent-config-management-ui-design.md](../specs/2026-06-08-agent-config-management-ui-design.md) §3.

---

## Task 1: GET /skills/registry

**Files:**
- Modify: `services/backend/src/agent_cloud_backend/api/skills.py`
- Test: `services/backend/tests/test_skills_api.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skills_api.py` (match the file's existing client fixture style — async `client`):

```python
async def test_list_registry_skills(client):
    r = await client.get("/skills/registry")
    assert r.status_code == 200
    assert "example-greeting" in r.json()  # 仓库内置 registry 技能
```

- [ ] **Step 2: Run → fail**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skills_api.py::test_list_registry_skills -q`
Expected: FAIL (404 — route missing). If it fails because `get_skill_registry_root` resolves to a path without the registry in the test env, override it in the test:
```python
    from agent_cloud_backend.skills.deps import get_skill_registry_root
    from pathlib import Path
    client.app.dependency_overrides[get_skill_registry_root] = lambda: Path(
        "src/agent_cloud_backend/skill_registry"
    )
```
(only add if needed).

- [ ] **Step 3: Implement the endpoint**

In `api/skills.py`, add (after `list_skills`, before `install_skill`; `Path` is already imported, `get_skill_registry_root` already imported):

```python
@router.get("/registry", response_model=list[str])
def list_registry_skills(registry_root: Path = Depends(get_skill_registry_root)):
    """列出 registry 里可安装的技能名(目录名 + 含 SKILL.md)。"""
    if not registry_root.exists():
        return []
    return sorted(
        p.name for p in registry_root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    )
```

- [ ] **Step 4: Run → pass + ruff**

Run: `cd services/backend && TESTCONTAINERS_RYUK_DISABLED=true uv run pytest tests/test_skills_api.py -q`
Expected: PASS.
Run: `uv run ruff check src/agent_cloud_backend/api/skills.py tests/test_skills_api.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add services/backend/src/agent_cloud_backend/api/skills.py services/backend/tests/test_skills_api.py
git commit -m "feat(backend): GET /skills/registry — list installable registry skills"
```

---

## Self-Review
- Spec coverage: §3 endpoint ✓. Route order: `/skills/registry` (GET) doesn't collide with `/skills/{skill_id}` (DELETE) or `/skills` (GET list). 
- No placeholders. Full code + commands.
