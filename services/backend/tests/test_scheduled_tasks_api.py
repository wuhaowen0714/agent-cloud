from datetime import UTC, datetime

from tests.conftest import register_user


async def _make_agent(auth_client) -> str:
    r = await auth_client.post("/agent-configs", json={"name": "a", "model": "m", "provider": "p"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_create_list_scoped(auth_client):
    aid = await _make_agent(auth_client)
    r = await auth_client.post(
        "/scheduled-tasks",
        json={
            "name": "每日新闻",
            "prompt": "总结新闻",
            "agent_config_id": aid,
            "schedule_kind": "cron",
            "schedule_expr": "0 9 * * *",
            "schedule_tz": "Asia/Shanghai",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "每日新闻"
    assert body["next_run_at"] is not None
    assert body["enabled"] is True

    lst = await auth_client.get("/scheduled-tasks")
    assert [t["name"] for t in lst.json()] == ["每日新闻"]


async def test_create_rejects_bad_schedule(auth_client):
    aid = await _make_agent(auth_client)
    r = await auth_client.post(
        "/scheduled-tasks",
        json={
            "name": "x",
            "prompt": "p",
            "agent_config_id": aid,
            "schedule_kind": "cron",
            "schedule_expr": "not a cron",
        },
    )
    assert r.status_code == 422


async def test_create_other_users_agent_404(auth_client, client):
    aid = await _make_agent(auth_client)
    other_access, _ = await register_user(client)
    r = await client.post(
        "/scheduled-tasks",
        headers={"Authorization": f"Bearer {other_access}"},
        json={
            "name": "x",
            "prompt": "p",
            "agent_config_id": aid,
            "schedule_kind": "interval",
            "schedule_expr": "600",
        },
    )
    assert r.status_code == 404  # agent 不属本人


async def test_patch_pause_resume_recomputes(auth_client):
    aid = await _make_agent(auth_client)
    tid = (
        await auth_client.post(
            "/scheduled-tasks",
            json={
                "name": "t",
                "prompt": "p",
                "agent_config_id": aid,
                "schedule_kind": "interval",
                "schedule_expr": "3600",
            },
        )
    ).json()["id"]
    r = await auth_client.patch(f"/scheduled-tasks/{tid}", json={"enabled": False})
    assert r.json()["enabled"] is False
    r = await auth_client.patch(f"/scheduled-tasks/{tid}", json={"enabled": True})
    assert r.json()["enabled"] is True
    assert r.json()["next_run_at"] is not None


async def test_run_now_sets_next_run_now(auth_client):
    aid = await _make_agent(auth_client)
    tid = (
        await auth_client.post(
            "/scheduled-tasks",
            json={
                "name": "t",
                "prompt": "p",
                "agent_config_id": aid,
                "schedule_kind": "cron",
                "schedule_expr": "0 9 * * *",
            },
        )
    ).json()["id"]
    r = await auth_client.post(f"/scheduled-tasks/{tid}/run-now")
    assert r.status_code == 200
    nxt = datetime.fromisoformat(r.json()["next_run_at"])
    assert nxt <= datetime.now(UTC)  # 立刻到期,轮询器会拾取


async def test_delete_and_404(auth_client):
    aid = await _make_agent(auth_client)
    tid = (
        await auth_client.post(
            "/scheduled-tasks",
            json={
                "name": "t",
                "prompt": "p",
                "agent_config_id": aid,
                "schedule_kind": "interval",
                "schedule_expr": "600",
            },
        )
    ).json()["id"]
    assert (await auth_client.delete(f"/scheduled-tasks/{tid}")).status_code == 204
    assert (
        await auth_client.patch(f"/scheduled-tasks/{tid}", json={"name": "z"})
    ).status_code == 404
