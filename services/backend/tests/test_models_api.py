import uuid


async def test_models_crud_idempotent_and_validation(auth_client):
    # 空列表
    r = await auth_client.get("/models")
    assert r.status_code == 200
    assert r.json() == []
    # 创建(trim)
    r = await auth_client.post("/models", json={"model": " GLM-5.1-Air "})
    assert r.status_code == 201
    row = r.json()
    assert row["model"] == "GLM-5.1-Air"
    # 重复幂等:同一行,不报错
    r2 = await auth_client.post("/models", json={"model": "GLM-5.1-Air"})
    assert r2.status_code == 201
    assert r2.json()["id"] == row["id"]
    # 列表可见(仅一条)
    assert [m["model"] for m in (await auth_client.get("/models")).json()] == ["GLM-5.1-Air"]
    # 校验:空/超长 → 422
    assert (await auth_client.post("/models", json={"model": "   "})).status_code == 422
    assert (await auth_client.post("/models", json={"model": "x" * 201})).status_code == 422
    # 删除 → 204,列表空;删不存在 → 404
    assert (await auth_client.delete(f"/models/{row['id']}")).status_code == 204
    assert (await auth_client.get("/models")).json() == []
    assert (await auth_client.delete(f"/models/{uuid.uuid4()}")).status_code == 404


async def test_models_cross_user_isolation_and_foreign_delete_404(auth_client):
    mid = (await auth_client.post("/models", json={"model": "mine"})).json()["id"]
    # 第二个用户(独立 token,按请求覆盖 Authorization)
    reg = await auth_client.post(
        "/auth/register", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert (await auth_client.get("/models", headers=h)).json() == []  # 隔离
    assert (await auth_client.delete(f"/models/{mid}", headers=h)).status_code == 404  # 他人 → 404
    assert [m["model"] for m in (await auth_client.get("/models")).json()] == ["mine"]  # 原样
